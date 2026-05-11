from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .bench_parser import BenchParser, Circuit
from .partitioner import FMPartitioner, PartitionResult
from .floorplanner import Floorplanner, FloorplanResult
from .placer import ForcedDirectedPlacer, PlacementResult
from .sta import STAEngine, STAResult
from .layout_engine import LayoutEngine, LayoutResult
from .compactor import ConstraintCompactor, CompactionResult
from .rc_extractor import RCExtractor, RCResult
from .gds_writer import GDSWriter


@dataclass
class CircuitFlowResult:
    circuit_name: str
    bench_path: Path
    partition: PartitionResult | None = None
    floorplan: FloorplanResult | None = None
    placement: PlacementResult | None = None
    sta: STAResult | None = None
    layout: LayoutResult | None = None
    compaction: CompactionResult | None = None
    rc: RCResult | None = None
    gds_path: Path | None = None
    figure_paths: dict[str, Path] = field(default_factory=dict)
    stage_times: dict[str, float] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    # Circuit snapshot before compaction modifies gate positions in-place
    _circ_before_compact: Circuit | None = field(default=None, repr=False)

    def to_dict(self) -> dict:
        def _safe(v):
            if v is None:
                return None
            if isinstance(v, Path):
                return str(v)
            if isinstance(v, dict):
                return {k: _safe(val) for k, val in v.items()}
            if isinstance(v, list):
                return [_safe(i) for i in v]
            if hasattr(v, "__dataclass_fields__"):
                # dataclass — only serialize simple fields
                out = {}
                for k in v.__dataclass_fields__:
                    if k.startswith("_"):
                        continue
                    val = getattr(v, k)
                    if isinstance(val, (str, int, float, bool, type(None))):
                        out[k] = val
                    elif isinstance(val, (list, dict)):
                        # skip large collections to keep JSON slim
                        out[k] = f"<{type(val).__name__} len={len(val)}>"
                return out
            return v

        return {
            "circuit_name": self.circuit_name,
            "stage_times": self.stage_times,
            "errors": self.errors,
            "gds_path": str(self.gds_path) if self.gds_path else None,
            "figure_count": len(self.figure_paths),
            "figure_paths": {k: str(v) for k, v in self.figure_paths.items()},
            "partition": _safe(self.partition),
            "floorplan": _safe(self.floorplan),
            "placement": _safe(self.placement),
            "sta": _safe(self.sta),
            "compaction": _safe(self.compaction),
            "rc": _safe(self.rc),
        }


class ISCAS89FlowRunner:
    """
    Orchestrates the complete ISCAS-89 physical design flow:
    parse → partition → floorplan → place → STA → layout → compact → RC → GDS II → visualize
    """

    def __init__(
        self,
        figures_dir: Path = Path("outputs/figures/iscas89"),
        gds_dir: Path = Path("outputs/gds"),
        num_partitions: int = 2,
        target_utilization: float = 0.65,
    ):
        self.figures_dir = Path(figures_dir)
        self.gds_dir = Path(gds_dir)
        self.num_partitions = num_partitions
        self.target_utilization = target_utilization

        self.figures_dir.mkdir(parents=True, exist_ok=True)
        self.gds_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def run_circuit(self, bench_path: Path) -> CircuitFlowResult:
        bench_path = Path(bench_path)
        result = CircuitFlowResult(
            circuit_name=bench_path.stem,
            bench_path=bench_path,
        )

        # 1. Parse
        t0 = time.perf_counter()
        circ = BenchParser().parse(bench_path)
        result.stage_times["parse"] = time.perf_counter() - t0
        print(f"  [parse]     {circ.name}: {len(circ.gates)} gates, "
              f"{len(circ.primary_inputs)} PIs, {len(circ.flip_flops)} FFs")

        # 2. Partition
        t0 = time.perf_counter()
        try:
            result.partition = FMPartitioner().partition(circ, k=self.num_partitions)
            result.stage_times["partition"] = time.perf_counter() - t0
            p = result.partition
            print(f"  [partition] cut_ratio={p.cut_ratio:.3f}, "
                  f"balance={p.balance:.3f}, iters={p.iterations}")
        except Exception as exc:
            result.errors["partition"] = str(exc)
            print(f"  [partition] ERROR: {exc}")

        # 3. Floorplan
        t0 = time.perf_counter()
        try:
            result.floorplan = Floorplanner(
                target_util=self.target_utilization
            ).plan(circ)
            result.stage_times["floorplan"] = time.perf_counter() - t0
            fp = result.floorplan
            print(f"  [floorplan] die={fp.die_w:.1f}×{fp.die_h:.1f}, "
                  f"util={fp.utilization:.1%}, rows={fp.num_rows}")
        except Exception as exc:
            result.errors["floorplan"] = str(exc)
            print(f"  [floorplan] ERROR: {exc}")

        # 4. Placement
        t0 = time.perf_counter()
        try:
            result.placement = ForcedDirectedPlacer().place(circ)
            result.stage_times["placement"] = time.perf_counter() - t0
            pl = result.placement
            print(f"  [placement] HPWL={pl.hpwl:.1f}, "
                  f"overflow={pl.overflow:.2%}, density={pl.density:.2%}")
        except Exception as exc:
            result.errors["placement"] = str(exc)
            print(f"  [placement] ERROR: {exc}")

        # 5. STA
        t0 = time.perf_counter()
        try:
            result.sta = STAEngine().run(circ)
            result.stage_times["sta"] = time.perf_counter() - t0
            st = result.sta
            print(f"  [sta]       WNS={st.wns_ps:.1f}ps, TNS={st.tns_ps:.1f}ps, "
                  f"depth={st.critical_path_depth}, violating={st.num_violating_paths}")
        except Exception as exc:
            result.errors["sta"] = str(exc)
            print(f"  [sta]       ERROR: {exc}")

        # 6. Layout
        t0 = time.perf_counter()
        try:
            result.layout = LayoutEngine().generate(circ)
            result.stage_times["layout"] = time.perf_counter() - t0
            ly = result.layout
            print(f"  [layout]    cells={ly.num_cells}, nets={len(ly.nets)}, "
                  f"die={ly.die_w:.1f}×{ly.die_h:.1f}")
        except Exception as exc:
            result.errors["layout"] = str(exc)
            print(f"  [layout]    ERROR: {exc}")

        # 7. Compaction (snapshot circ BEFORE, since compact modifies gate.x/y in-place)
        t0 = time.perf_counter()
        try:
            fp_result = result.floorplan
            orig_w = fp_result.die_w if fp_result else 50.0
            orig_h = fp_result.die_h if fp_result else 50.0
            result._circ_before_compact = copy.deepcopy(circ)
            result.compaction = ConstraintCompactor().compact(circ, orig_w, orig_h)
            result.stage_times["compaction"] = time.perf_counter() - t0
            cp = result.compaction
            print(f"  [compaction] area_red={cp.area_reduction_pct:.1f}%, "
                  f"ws={cp.whitespace_pct:.1f}%, "
                  f"new={cp.compacted_die_w:.1f}×{cp.compacted_die_h:.1f}")
        except Exception as exc:
            result.errors["compaction"] = str(exc)
            print(f"  [compaction] ERROR: {exc}")

        # 8. RC Extraction
        t0 = time.perf_counter()
        try:
            result.rc = RCExtractor().extract(circ)
            result.stage_times["rc_extraction"] = time.perf_counter() - t0
            rc = result.rc
            print(f"  [rc_extract] WL={rc.total_wirelength_um:.1f}μm, "
                  f"max_delay={rc.max_elmore_delay_ps:.1f}ps, "
                  f"nets={len(rc.nets)}")
        except Exception as exc:
            result.errors["rc_extraction"] = str(exc)
            print(f"  [rc_extract] ERROR: {exc}")

        # 9. GDS II
        t0 = time.perf_counter()
        try:
            if result.layout:
                gds_path = self.gds_dir / f"{circ.name}.gds"
                GDSWriter().write(result.layout, gds_path)
                result.gds_path = gds_path
                result.stage_times["gds"] = time.perf_counter() - t0
                print(f"  [gds]       {gds_path} ({gds_path.stat().st_size} bytes)")
        except Exception as exc:
            result.errors["gds"] = str(exc)
            print(f"  [gds]       ERROR: {exc}")

        # 10. Visualize (circ is now post-compaction)
        self._visualize(circ, result)

        return result

    # ------------------------------------------------------------------
    def _visualize(self, circ: Circuit, result: CircuitFlowResult) -> None:
        try:
            from .visualizer import ISCAS89Visualizer
        except ImportError as exc:
            print(f"  [viz]       skipped (import error: {exc})")
            return

        cname = circ.name
        fdir = self.figures_dir / cname
        fdir.mkdir(parents=True, exist_ok=True)
        viz = ISCAS89Visualizer(output_dir=fdir)

        def _s(method_name: str, tag: str, *args, **kwargs) -> None:
            try:
                t0 = time.perf_counter()
                path = getattr(viz, method_name)(*args, **kwargs)
                if path:
                    result.figure_paths[tag] = Path(path)
                print(f"  [viz:{tag:<18s}] {time.perf_counter()-t0:.2f}s")
            except Exception as exc:
                result.errors[f"viz_{tag}"] = str(exc)
                print(f"  [viz:{tag:<18s}] ERROR: {exc}")

        # 1. Circuit stats — expects list[dict]
        _s("plot_circuit_stats", "circuit_stats", [_circuit_stats_dict(circ)])

        # 2. Partition — (circ, part)
        if result.partition:
            _s("plot_partition", "partition", circ, result.partition)

        # 3. Floorplan — (fp, circ)  ← fp is first arg
        if result.floorplan:
            _s("plot_floorplan", "floorplan", result.floorplan, circ)

        # 4. Placement — (circ, pr)
        if result.placement:
            _s("plot_placement", "placement", circ, result.placement)

        # 5. STA — (sta, circ)  ← sta is first arg
        if result.sta:
            _s("plot_sta", "sta", result.sta, circ)
            _s("plot_critical_path", "critical_path", result.sta, circ)

        # 6. Layout — (layout) only
        if result.layout:
            _s("plot_layout", "layout", result.layout)

        # 7. Compaction — (comp, circ_before, circ_after)
        if result.compaction:
            circ_before = result._circ_before_compact or circ
            _s("plot_compaction", "compaction",
               result.compaction, circ_before, circ)

        # 8. RC extraction — (rc) only
        if result.rc:
            _s("plot_rc_extraction", "rc_extraction", result.rc)

        # 9. GDS preview — (layout, gds_path)
        if result.layout and result.gds_path:
            _s("plot_gds_preview", "gds_preview", result.layout, result.gds_path)

    # ------------------------------------------------------------------
    def run_all(
        self, bench_paths: list[Path]
    ) -> tuple[list[CircuitFlowResult], Path]:
        all_results: list[CircuitFlowResult] = []
        for bp in bench_paths:
            print(f"\n{'='*60}")
            print(f" Circuit: {bp.stem}")
            print(f"{'='*60}")
            r = self.run_circuit(bp)
            all_results.append(r)

        # Summary visualizations across all circuits
        self._summary_plots(all_results)

        # Persist JSON summary
        summary_path = self.figures_dir.parent / "iscas89_summary.json"
        summary = [r.to_dict() for r in all_results]
        summary_path.write_text(json.dumps(summary, indent=2, default=str))
        print(f"\n[summary] JSON → {summary_path}")

        return all_results, summary_path

    # ------------------------------------------------------------------
    def _summary_plots(self, results: list[CircuitFlowResult]) -> None:
        try:
            from .visualizer import ISCAS89Visualizer
        except ImportError as exc:
            print(f"[summary viz] skipped: {exc}")
            return

        # Re-parse circuits for stats (we only need PI/FF counts)
        circuits_map: dict[str, Circuit] = {}
        for r in results:
            try:
                circuits_map[r.circuit_name] = BenchParser().parse(r.bench_path)
            except Exception:
                pass

        viz = ISCAS89Visualizer(output_dir=self.figures_dir)

        # Build list[dict] for plot_multi_circuit_comparison
        comparison_rows = []
        for r in results:
            comparison_rows.append({
                "circuit": r.circuit_name,
                "wns_ps": r.sta.wns_ps if r.sta else 0.0,
                "max_arrival_ps": r.sta.max_arrival_ps if r.sta else 0.0,
                "hpwl": r.placement.improved_hpwl if r.placement else 0.0,
                "area_reduction_pct": r.compaction.area_reduction_pct
                                       if r.compaction else 0.0,
                "total_wire_um": r.rc.total_wirelength_um if r.rc else 0.0,
            })

        # Build list[dict] for plot_results_table
        table_rows = []
        for r in results:
            circ = circuits_map.get(r.circuit_name)
            table_rows.append({
                "circuit": r.circuit_name,
                "ffs": len(circ.flip_flops) if circ else 0,
                "gates": len(circ.gates) if circ else 0,
                "partitions": r.partition.k if r.partition else 0,
                "hpwl": r.placement.improved_hpwl if r.placement else 0.0,
                "wns_ps": r.sta.wns_ps if r.sta else 0.0,
                "tns_ps": r.sta.tns_ps if r.sta else 0.0,
                "total_wire_um": r.rc.total_wirelength_um if r.rc else 0.0,
                "area_reduction_pct": r.compaction.area_reduction_pct
                                       if r.compaction else 0.0,
                "max_elmore_ps": r.rc.max_elmore_delay_ps if r.rc else 0.0,
            })

        for fn_name, tag, arg in [
            ("plot_multi_circuit_comparison", "multi_circuit_comparison", comparison_rows),
            ("plot_results_table", "results_table", table_rows),
        ]:
            try:
                t0 = time.perf_counter()
                getattr(viz, fn_name)(arg)
                print(f"[summary:{tag}] saved ({time.perf_counter()-t0:.2f}s)")
            except Exception as exc:
                print(f"[summary:{tag}] ERROR: {exc}")


# ---------------------------------------------------------------------------
def _circuit_stats_dict(circ: Circuit) -> dict:
    comb_gates = sum(
        1 for g in circ.gates.values() if not g.is_ff
    )
    return {
        "name": circ.name,
        "primary_inputs": len(circ.primary_inputs),
        "flip_flops": len(circ.flip_flops),
        "combinational_gates": comb_gates,
    }
