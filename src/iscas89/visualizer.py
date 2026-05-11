from __future__ import annotations
import math
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.cm as cm
import numpy as np

from .bench_parser import Circuit
from .partitioner import PartitionResult
from .floorplanner import FloorplanResult
from .placer import PlacementResult
from .sta import STAResult, TimingNode
from .layout_engine import LayoutResult
from .compactor import CompactionResult
from .rc_extractor import RCResult

_STYLE = {
    "figure.facecolor": "white",
    "axes.facecolor":   "white",
    "axes.edgecolor":   "#333333",
    "axes.grid":        True,
    "grid.color":       "#e8e8e8",
    "grid.linewidth":   0.5,
    "font.family":      "DejaVu Sans",
    "font.size":        10,
    "axes.titlesize":   12,
    "axes.labelsize":   10,
    "legend.fontsize":  8,
    "savefig.facecolor": "white",
    "savefig.dpi":      180,
    "savefig.bbox":     "tight",
    "figure.constrained_layout.use": True,
}
_PALETTE = ["#1565C0","#C62828","#2E7D32","#F57F17",
            "#6A1B9A","#00838F","#558B2F","#E65100"]


def _apply_style():
    plt.rcParams.update(_STYLE)


def _save(fig, path: Path) -> Path:
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


class ISCAS89Visualizer:

    def __init__(self, output_dir: Path):
        self.out = Path(output_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        _apply_style()

    # ── 1. Circuit statistics bar chart ──────────────────────────────────────
    def plot_circuit_stats(
        self, stats_list: list[dict], fname: str = "circuit_stats.png"
    ) -> Path:
        names = [s["name"] for s in stats_list]
        pis   = [s["primary_inputs"]      for s in stats_list]
        ffs   = [s["flip_flops"]          for s in stats_list]
        gates = [s["combinational_gates"] for s in stats_list]

        x = np.arange(len(names))
        w = 0.25
        fig, ax = plt.subplots(figsize=(max(6, len(names)*1.4), 5))
        ax.bar(x - w, pis,   w, label="Primary Inputs",     color=_PALETTE[0], alpha=0.85)
        ax.bar(x,     ffs,   w, label="Flip-Flops",         color=_PALETTE[1], alpha=0.85)
        ax.bar(x + w, gates, w, label="Comb. Gates",        color=_PALETTE[2], alpha=0.85)
        ax.set_xticks(x); ax.set_xticklabels(names)
        ax.set_ylabel("Count"); ax.set_title("ISCAS-89 Circuit Statistics")
        ax.legend(loc="upper left")
        for bar_group in [ax.patches[:len(names)], ax.patches[len(names):2*len(names)],
                           ax.patches[2*len(names):]]:
            for bar in bar_group:
                h = bar.get_height()
                if h > 0:
                    ax.annotate(str(int(h)),
                                xy=(bar.get_x() + bar.get_width()/2, h),
                                xytext=(0, 2), textcoords="offset points",
                                ha="center", fontsize=7)
        return _save(fig, self.out / fname)

    # ── 2. Partitioning plot ──────────────────────────────────────────────────
    def plot_partition(
        self, circ: Circuit, part: PartitionResult,
        fname: str | None = None
    ) -> Path:
        fname = fname or f"{circ.name}_partition.png"
        fig, axes = plt.subplots(1, 2, figsize=(12, 5))

        ax = axes[0]
        colors_map = {0: _PALETTE[0], 1: _PALETTE[1], 2: _PALETTE[2], 3: _PALETTE[3]}
        for name, gate in circ.gates.items():
            c = colors_map.get(gate.partition % 4, "#607D8B")
            ax.scatter(gate.x, gate.y, c=c, s=40, zorder=3, alpha=0.8)
        patches = [mpatches.Patch(color=colors_map.get(i % 4, "#607D8B"),
                                    label=f"P{i} ({part.partition_sizes[i]} cells)")
                    for i in range(part.k)]
        ax.legend(handles=patches, loc="upper right", fontsize=8)
        ax.set_title(f"{circ.name} — {part.k}-way Partitioning")
        ax.set_xlabel("X (cell units)"); ax.set_ylabel("Y (cell units)")

        # Pie chart of partition sizes
        ax2 = axes[1]
        sizes = part.partition_sizes
        explode = [0.05] * len(sizes)
        wedge_colors = [colors_map.get(i % 4, "#607D8B") for i in range(len(sizes))]
        ax2.pie(sizes, labels=[f"P{i}" for i in range(len(sizes))],
                 autopct="%1.1f%%", startangle=90, explode=explode,
                 colors=wedge_colors)
        ax2.set_title(f"Cut nets: {part.cut_nets}/{part.total_nets} "
                       f"({part.cut_ratio*100:.1f}%)  Balance: {part.balance:.2f}")
        return _save(fig, self.out / fname)

    # ── 3. Floorplan plot ─────────────────────────────────────────────────────
    def plot_floorplan(
        self, fp: FloorplanResult, circ: Circuit,
        fname: str | None = None
    ) -> Path:
        fname = fname or f"{circ.name}_floorplan.png"
        fig, ax = plt.subplots(figsize=(8, 7))
        color_map = [_PALETTE[i % len(_PALETTE)] for i in range(len(fp.blocks))]
        for blk, color in zip(fp.blocks, color_map):
            rect = mpatches.FancyBboxPatch(
                (blk.x, blk.y), blk.w, blk.h,
                boxstyle="round,pad=0.05",
                facecolor=color, edgecolor="white",
                linewidth=1.5, alpha=0.75, zorder=2
            )
            ax.add_patch(rect)
            ax.text(blk.cx, blk.cy,
                     f"{blk.name}\n{blk.cell_count} cells",
                     ha="center", va="center", fontsize=8,
                     fontweight="bold", color="white", zorder=3)
        ax.set_xlim(-0.5, fp.die_w + 0.5)
        ax.set_ylim(-0.5, fp.die_h + 0.5)
        # Die outline
        die_rect = mpatches.Rectangle(
            (0, 0), fp.die_w, fp.die_h,
            fill=False, edgecolor="#333", linewidth=2, linestyle="--", zorder=1
        )
        ax.add_patch(die_rect)
        ax.set_title(f"{circ.name} Floorplan  |  "
                      f"Die {fp.die_w:.1f}×{fp.die_h:.1f}  "
                      f"Util={fp.utilization*100:.1f}%  "
                      f"AR={fp.aspect_ratio:.2f}")
        ax.set_xlabel("X (cell units)"); ax.set_ylabel("Y (cell units)")
        ax.set_aspect("equal")
        return _save(fig, self.out / fname)

    # ── 4. Placement heatmap ──────────────────────────────────────────────────
    def plot_placement(
        self, circ: Circuit, pr: PlacementResult,
        fname: str | None = None
    ) -> Path:
        fname = fname or f"{circ.name}_placement.png"
        fig, axes = plt.subplots(1, 2, figsize=(13, 5))

        # Scatter plot with gate-type colouring
        ax = axes[0]
        ctype_map = {
            "DFF": "#B71C1C", "NOT": "#F57F17", "INV": "#F57F17",
            "AND": "#1565C0", "NAND": "#0288D1",
            "OR": "#2E7D32", "NOR": "#66BB6A",
            "BUFF": "#FBC02D",
        }
        for name, gate in circ.gates.items():
            c = ctype_map.get(gate.gtype, "#607D8B")
            size = 80 if gate.is_ff else 30
            marker = "s" if gate.is_ff else "o"
            ax.scatter(gate.x, gate.y, c=c, s=size, marker=marker,
                        zorder=3, alpha=0.85)
        # Row lines
        for r in range(pr.num_rows + 1):
            ax.axhline(r * 1.0, color="#ddd", linewidth=0.5, zorder=1)
        ax.set_xlim(-1, pr.die_w + 1)
        ax.set_ylim(-1, pr.die_h + 1)
        ax.set_title(f"{circ.name} Placement\n"
                      f"HPWL={pr.improved_hpwl:.1f}  Δ={pr.hpwl_improvement_pct:.1f}%  "
                      f"OF={pr.overflow*100:.1f}%")
        ax.set_xlabel("X (cell units)"); ax.set_ylabel("Y (cell units)")

        # Density heatmap
        ax2 = axes[1]
        if pr.num_rows > 0 and pr.cells_per_row > 0:
            grid = np.zeros((pr.num_rows, pr.cells_per_row))
            for gate in circ.gates.values():
                r = min(pr.num_rows - 1, int(gate.y))
                c = min(pr.cells_per_row - 1, int(gate.x))
                if 0 <= r < pr.num_rows and 0 <= c < pr.cells_per_row:
                    grid[r, c] += 1
            im = ax2.imshow(grid, cmap="YlOrRd", origin="lower", aspect="auto",
                              interpolation="nearest")
            plt.colorbar(im, ax=ax2, label="Cells / slot")
        ax2.set_title(f"{circ.name} Placement Density Heatmap")
        ax2.set_xlabel("Column"); ax2.set_ylabel("Row")
        return _save(fig, self.out / fname)

    # ── 5. STA plots ──────────────────────────────────────────────────────────
    def plot_sta(
        self, sta: STAResult, circ: Circuit,
        fname: str | None = None
    ) -> Path:
        fname = fname or f"{circ.name}_sta.png"
        fig, axes = plt.subplots(1, 3, figsize=(16, 5))

        # Slack distribution
        ax = axes[0]
        slacks = [tn.slack for tn in sta.timing_nodes.values()]
        ax.hist(slacks, bins=30, color=_PALETTE[0], edgecolor="white",
                 alpha=0.85)
        ax.axvline(0, color="red", linewidth=1.5, linestyle="--", label="0 ns boundary")
        ax.axvline(sta.wns_ps, color="#F57F17", linewidth=1.5, linestyle="--",
                    label=f"WNS={sta.wns_ps:.0f}ps")
        ax.set_xlabel("Slack (ps)"); ax.set_ylabel("Gate count")
        ax.set_title(f"{circ.name} Slack Distribution")
        ax.legend(fontsize=8)

        # Arrival time vs level
        ax2 = axes[1]
        levels = [circ.levels.get(n, 0) for n in sta.timing_nodes]
        arrivals = [tn.arrival for tn in sta.timing_nodes.values()]
        scatter = ax2.scatter(levels, arrivals, c=arrivals, cmap="plasma",
                               s=20, alpha=0.7, zorder=3)
        plt.colorbar(scatter, ax=ax2, label="Arrival (ps)")
        ax2.set_xlabel("Logic Level"); ax2.set_ylabel("Arrival Time (ps)")
        ax2.set_title(f"{circ.name} Arrival Time vs Logic Level")

        # Slack histogram buckets
        ax3 = axes[2]
        buckets = sta.slack_histogram
        bnames = list(buckets.keys())
        bvals  = list(buckets.values())
        colors = ["#C62828" if "<" in b else "#2E7D32" for b in bnames]
        ax3.barh(bnames, bvals, color=colors, alpha=0.85)
        ax3.set_xlabel("Gate count")
        ax3.set_title(f"Slack Histogram\nWNS={sta.wns_ps:.0f}ps  "
                       f"TNS={sta.tns_ps:.0f}ps  "
                       f"Viol={sta.num_violating_paths}")
        for i, v in enumerate(bvals):
            if v > 0:
                ax3.text(v + 0.3, i, str(v), va="center", fontsize=8)
        return _save(fig, self.out / fname)

    # ── 6. Critical path ──────────────────────────────────────────────────────
    def plot_critical_path(
        self, sta: STAResult, circ: Circuit,
        fname: str | None = None
    ) -> Path:
        fname = fname or f"{circ.name}_critical_path.png"
        cp = sta.critical_path
        if not cp:
            fig, ax = plt.subplots(figsize=(6, 3))
            ax.text(0.5, 0.5, "No critical path found", ha="center", va="center")
            ax.set_title(f"{circ.name} Critical Path")
            return _save(fig, self.out / fname)

        arrivals = [sta.timing_nodes.get(n, TimingNode(n)).arrival for n in cp]
        slacks   = [sta.timing_nodes.get(n, TimingNode(n)).slack   for n in cp]
        labels   = [n if len(n) <= 6 else n[:6] for n in cp]

        fig, axes = plt.subplots(1, 2, figsize=(14, 4))

        ax = axes[0]
        ax.plot(range(len(cp)), arrivals, marker="o", color=_PALETTE[0],
                 linewidth=2, markersize=7, zorder=3)
        ax.fill_between(range(len(cp)), arrivals, alpha=0.15, color=_PALETTE[0])
        ax.axhline(sta.clock_period_ps, color="red", linestyle="--",
                    linewidth=1, label=f"Clock period ({sta.clock_period_ps:.0f}ps)")
        ax.set_xticks(range(len(cp)))
        ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
        ax.set_ylabel("Arrival Time (ps)")
        ax.set_title(f"{circ.name} Critical Path Arrival\n"
                      f"({len(cp)} stages,  WNS={sta.wns_ps:.0f}ps)")
        ax.legend(fontsize=8)

        ax2 = axes[1]
        colors = ["#C62828" if s < 0 else "#2E7D32" for s in slacks]
        ax2.bar(range(len(cp)), slacks, color=colors, alpha=0.85)
        ax2.axhline(0, color="black", linewidth=0.8)
        ax2.set_xticks(range(len(cp)))
        ax2.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
        ax2.set_ylabel("Slack (ps)")
        ax2.set_title("Per-node Slack Along Critical Path")
        return _save(fig, self.out / fname)

    # ── 7. Layout visualization ───────────────────────────────────────────────
    def plot_layout(
        self, layout: LayoutResult,
        fname: str | None = None
    ) -> Path:
        fname = fname or f"{layout.circuit_name}_layout.png"
        fig, ax = plt.subplots(figsize=(10, 8))
        ax.set_facecolor("#FAFAFA")

        # Die outline
        die_rect = mpatches.Rectangle(
            (0, 0), layout.die_w, layout.die_h,
            fill=False, edgecolor="#333", linewidth=2, zorder=1
        )
        ax.add_patch(die_rect)

        # Row stripes
        for r in range(layout.num_rows + 1):
            y = r
            fc = "#F3F4F6" if r % 2 == 0 else "white"
            ax.axhspan(y, y + 1, color=fc, alpha=0.5, zorder=0)

        # Draw wires first (behind cells)
        for net in layout.nets:
            for x1, y1, x2, y2 in net.segments:
                ax.plot([x1, x2], [y1, y2], color="#BDBDBD",
                         linewidth=0.4, zorder=1, alpha=0.5)

        # Draw cells
        ctype_color = {
            "DFF": "#B71C1C", "NOT": "#F57F17", "INV": "#F57F17",
            "AND": "#1565C0", "NAND": "#0288D1",
            "OR": "#2E7D32",  "NOR": "#66BB6A",
            "BUFF": "#FBC02D", "PI": "#78909C",
        }
        for cell in layout.cells:
            ec = "white"
            fc = ctype_color.get(cell.gtype, "#607D8B")
            lw = 1.5 if cell.is_ff else 0.7
            rect = mpatches.FancyBboxPatch(
                (cell.x, cell.y), cell.w, cell.h,
                boxstyle="round,pad=0.02",
                facecolor=fc, edgecolor=ec, linewidth=lw,
                alpha=0.88, zorder=3
            )
            ax.add_patch(rect)
            if cell.w > 0.5:
                ax.text(cell.x + cell.w / 2, cell.y + cell.h / 2,
                         cell.gtype[:3],
                         ha="center", va="center",
                         fontsize=max(4, min(7, 40 / max(1, layout.num_cells / 10))),
                         color="white", fontweight="bold", zorder=4)

        ax.set_xlim(-2.5, layout.die_w + 0.5)
        ax.set_ylim(-0.5, layout.die_h + 0.5)
        ax.set_aspect("equal")
        ax.set_xlabel("X (cell units)"); ax.set_ylabel("Y (cell units)")
        ax.set_title(f"{layout.circuit_name} Standard-Cell Layout\n"
                      f"{layout.num_cells} gates  |  "
                      f"{layout.num_ff} FFs  |  "
                      f"{layout.num_rows} rows")

        # Legend
        legend_items = [
            mpatches.Patch(color=ctype_color.get(t, "#607D8B"), label=t)
            for t in ["DFF", "AND", "NAND", "OR", "NOR", "NOT", "BUFF"]
        ]
        ax.legend(handles=legend_items, loc="upper right",
                   fontsize=7, ncol=2, framealpha=0.9)
        return _save(fig, self.out / fname)

    # ── 8. Compaction before/after ────────────────────────────────────────────
    def plot_compaction(
        self, comp: CompactionResult,
        circ_before: Circuit, circ_after: Circuit,
        fname: str | None = None
    ) -> Path:
        fname = fname or f"{comp.circuit_name}_compaction.png"
        fig, axes = plt.subplots(1, 3, figsize=(16, 5))

        # Before
        for ax, gates_src, title in [
            (axes[0], circ_before.gates, "Before Compaction"),
            (axes[1], circ_after.gates,  "After Compaction"),
        ]:
            for gate in gates_src.values():
                c = "#1565C0" if gate.is_ff else "#2E7D32"
                rect = mpatches.Rectangle(
                    (gate.x, gate.y), 0.85, 0.7,
                    facecolor=c, edgecolor="white",
                    linewidth=0.5, alpha=0.75
                )
                ax.add_patch(rect)
            ax.set_xlim(-0.5, max(g.x for g in gates_src.values()) + 2 if gates_src else 2)
            ax.set_ylim(-0.5, max(g.y for g in gates_src.values()) + 2 if gates_src else 2)
            ax.set_aspect("equal")
            ax.set_title(title)
            ax.set_xlabel("X"); ax.set_ylabel("Y")

        # Summary bars
        ax3 = axes[2]
        metrics = {
            "Original W": comp.original_die_w,
            "Compacted W": comp.compacted_die_w,
            "Original H": comp.original_die_h,
            "Compacted H": comp.compacted_die_h,
        }
        colors = ["#C62828", "#2E7D32", "#C62828", "#2E7D32"]
        ax3.bar(range(len(metrics)), list(metrics.values()),
                 color=colors, alpha=0.85, width=0.6)
        ax3.set_xticks(range(len(metrics)))
        ax3.set_xticklabels(list(metrics.keys()), rotation=25, ha="right")
        ax3.set_ylabel("Size (cell units)")
        ax3.set_title(f"Compaction Summary\n"
                       f"Area Reduction: {comp.area_reduction_pct:.1f}%  "
                       f"Whitespace: {comp.whitespace_pct:.1f}%")
        for i, v in enumerate(metrics.values()):
            ax3.text(i, v + 0.1, f"{v:.1f}", ha="center", fontsize=8)
        return _save(fig, self.out / fname)

    # ── 9. RC extraction plots ────────────────────────────────────────────────
    def plot_rc_extraction(
        self, rc: RCResult, fname: str | None = None
    ) -> Path:
        fname = fname or f"{rc.circuit_name}_rc_extraction.png"
        if not rc.nets:
            fig, ax = plt.subplots()
            ax.text(0.5, 0.5, "No nets", ha="center")
            return _save(fig, self.out / fname)

        fig, axes = plt.subplots(1, 3, figsize=(16, 5))

        # Elmore delay distribution
        ax = axes[0]
        delays = [n.elmore_delay_ps for n in rc.nets]
        ax.hist(delays, bins=20, color=_PALETTE[0], edgecolor="white", alpha=0.85)
        ax.axvline(rc.avg_elmore_delay_ps, color="red", linestyle="--",
                    linewidth=1.5, label=f"Avg={rc.avg_elmore_delay_ps:.1f}ps")
        ax.axvline(rc.max_elmore_delay_ps, color="#F57F17", linestyle="--",
                    linewidth=1.5, label=f"Max={rc.max_elmore_delay_ps:.1f}ps")
        ax.set_xlabel("Elmore Delay (ps)"); ax.set_ylabel("Net count")
        ax.set_title(f"{rc.circuit_name}\nElmore Delay Distribution")
        ax.legend(fontsize=8)

        # Wire length distribution
        ax2 = axes[1]
        lengths = [n.length_um for n in rc.nets]
        ax2.hist(lengths, bins=20, color=_PALETTE[2], edgecolor="white", alpha=0.85)
        ax2.set_xlabel("Wire Length (μm)"); ax2.set_ylabel("Net count")
        ax2.set_title(f"Wire Length Distribution\n"
                       f"Total={rc.total_wirelength_um:.1f}μm")

        # Top 10 critical nets
        ax3 = axes[2]
        top_nets = sorted(rc.nets, key=lambda n: n.elmore_delay_ps, reverse=True)[:10]
        names = [n.name for n in top_nets]
        delays_top = [n.elmore_delay_ps for n in top_nets]
        bars = ax3.barh(names, delays_top, color=_PALETTE[1], alpha=0.85)
        ax3.set_xlabel("Elmore Delay (ps)")
        ax3.set_title(f"Top 10 Critical Nets by Delay\n"
                       f"R={rc.total_resistance_kohm:.2f}kΩ  "
                       f"C={rc.total_capacitance_ff:.1f}fF")
        for bar in bars:
            w = bar.get_width()
            ax3.text(w + 0.1, bar.get_y() + bar.get_height() / 2,
                      f"{w:.1f}", va="center", fontsize=7)
        return _save(fig, self.out / fname)

    # ── 10. GDS II preview ────────────────────────────────────────────────────
    def plot_gds_preview(
        self, layout: LayoutResult, gds_path: Path,
        fname: str | None = None
    ) -> Path:
        fname = fname or f"{layout.circuit_name}_gds_preview.png"
        fig, ax = plt.subplots(figsize=(9, 8))
        ax.set_facecolor("#111111")

        _LAYER_COLOR = {
            0: ("#1565C0", 0.7),   # gates
            1: ("#66BB6A", 0.4),   # wires
            2: ("#B71C1C", 0.8),   # FF
            4: ("#78909C", 0.5),   # PI
            5: ("#FBC02D", 0.0),   # text (skip)
            10: ("#FFFFFF", 0.15), # die outline
        }

        for cell in layout.cells:
            layer = 2 if cell.is_ff else (4 if cell.is_pi else 0)
            color, alpha = _LAYER_COLOR.get(layer, ("#607D8B", 0.6))
            rect = mpatches.Rectangle(
                (cell.x * 0.38, cell.y * 0.38),
                cell.w * 0.38, cell.h * 0.38,
                facecolor=color, edgecolor="#FFFFFF",
                linewidth=0.3, alpha=alpha, zorder=3
            )
            ax.add_patch(rect)

        for net in layout.nets:
            for x1, y1, x2, y2 in net.segments:
                ax.plot([x1 * 0.38, x2 * 0.38],
                         [y1 * 0.38, y2 * 0.38],
                         color="#66BB6A", linewidth=0.3,
                         alpha=0.4, zorder=2)

        die_rect = mpatches.Rectangle(
            (0, 0), layout.die_w * 0.38, layout.die_h * 0.38,
            fill=False, edgecolor="white", linewidth=1.5, zorder=1
        )
        ax.add_patch(die_rect)

        gds_size_kb = gds_path.stat().st_size / 1024 if gds_path.exists() else 0
        ax.set_xlim(-0.5, layout.die_w * 0.38 + 0.5)
        ax.set_ylim(-0.5, layout.die_h * 0.38 + 0.5)
        ax.set_aspect("equal")
        ax.set_xlabel("X (μm)", color="white")
        ax.set_ylabel("Y (μm)", color="white")
        ax.tick_params(colors="white")
        ax.spines[:].set_color("white")
        ax.set_title(f"{layout.circuit_name} GDS II Preview\n"
                      f"File: {gds_path.name}  ({gds_size_kb:.1f} KB)",
                      color="white")
        ax.set_facecolor("#111111")
        fig.patch.set_facecolor("#111111")

        legend_items = [
            mpatches.Patch(color="#1565C0", label="Gate (L0)"),
            mpatches.Patch(color="#B71C1C", label="DFF (L2)"),
            mpatches.Patch(color="#66BB6A", label="Wire (L1)"),
            mpatches.Patch(color="white",   label="Die (L10)"),
        ]
        ax.legend(handles=legend_items, loc="upper right",
                   fontsize=8, framealpha=0.3, labelcolor="white",
                   facecolor="#333")
        # Note: save with dark bg for GDS preview only
        fig.savefig(self.out / fname, facecolor="#111111", dpi=180, bbox_inches="tight")
        plt.close(fig)
        return self.out / fname

    # ── 11. Multi-circuit comparison ─────────────────────────────────────────
    def plot_multi_circuit_comparison(
        self,
        results: list[dict],
        fname: str = "iscas89_summary.png",
    ) -> Path:
        names = [r["circuit"] for r in results]
        metrics = {
            "WNS (ps)":             [r["wns_ps"]            for r in results],
            "Max Arrival (ps)":     [r["max_arrival_ps"]    for r in results],
            "HPWL (units)":         [r["hpwl"]              for r in results],
            "Area Reduction (%)":   [r["area_reduction_pct"] for r in results],
            "Total Wire (μm)":      [r["total_wire_um"]     for r in results],
        }
        fig, axes = plt.subplots(1, len(metrics), figsize=(4 * len(metrics), 5))
        if len(metrics) == 1:
            axes = [axes]
        for ax, (metric, vals) in zip(axes, metrics.items()):
            colors = [_PALETTE[i % len(_PALETTE)] for i in range(len(names))]
            ax.bar(names, vals, color=colors, alpha=0.85, width=0.6)
            ax.set_title(metric, fontsize=9)
            ax.set_xticklabels(names, rotation=30, ha="right", fontsize=8)
            for i, v in enumerate(vals):
                ax.text(i, v + max(vals) * 0.01, f"{v:.1f}",
                         ha="center", fontsize=7)
        fig.suptitle("ISCAS-89 Physical Design Results", fontsize=13, y=1.01)
        return _save(fig, self.out / fname)

    # ── 12. Summary table ─────────────────────────────────────────────────────
    def plot_results_table(
        self, rows: list[dict], fname: str = "iscas89_table.png"
    ) -> Path:
        cols = ["Circuit", "FFs", "Gates", "Partitions",
                "HPWL", "WNS(ps)", "TNS(ps)", "Wire(μm)",
                "Area Red.%", "Elmore Max(ps)"]
        data = []
        for r in rows:
            data.append([
                r.get("circuit", ""),
                str(r.get("ffs", "")),
                str(r.get("gates", "")),
                str(r.get("partitions", "")),
                f"{r.get('hpwl', 0):.1f}",
                f"{r.get('wns_ps', 0):.0f}",
                f"{r.get('tns_ps', 0):.0f}",
                f"{r.get('total_wire_um', 0):.1f}",
                f"{r.get('area_reduction_pct', 0):.1f}%",
                f"{r.get('max_elmore_ps', 0):.1f}",
            ])

        fig, ax = plt.subplots(
            figsize=(max(12, len(cols) * 1.4), max(3, len(rows) * 0.6))
        )
        ax.axis("off")
        tbl = ax.table(
            cellText=data, colLabels=cols,
            cellLoc="center", loc="center"
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(8.5)
        tbl.scale(1.15, 1.5)
        for (row, col), cell in tbl.get_celld().items():
            if row == 0:
                cell.set_facecolor("#1565C0")
                cell.set_text_props(color="white", fontweight="bold")
            elif row % 2 == 1:
                cell.set_facecolor("#E3F2FD")
            else:
                cell.set_facecolor("white")
        ax.set_title("ISCAS-89 Physical Design Summary",
                      fontsize=13, pad=12, fontweight="bold")
        return _save(fig, self.out / fname)
