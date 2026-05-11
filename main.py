#!/usr/bin/env python3
"""
Next-Generation Physical Design Framework
Command-line entry point.

Usage:
  python main.py run      --design gcd --config configs/base.yaml
  python main.py sweep    --manifest configs/benchmarks/ipsd_manifest.yaml
  python main.py ablation --config configs/base.yaml
  python main.py report   --runs-dir outputs/runs
  python main.py validate --manifest configs/benchmarks/ipsd_manifest.yaml
"""
from __future__ import annotations
import argparse
import logging
import sys
from pathlib import Path

import yaml

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=_LOG_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def load_config(path: str | None) -> dict:
    base = Path("configs/base.yaml")
    cfg: dict = {}
    if base.exists():
        cfg.update(yaml.safe_load(base.read_text()) or {})
    if path:
        p = Path(path)
        if p.exists():
            cfg.update(yaml.safe_load(p.read_text()) or {})
        else:
            logging.warning("Config file not found: %s — using defaults", path)
    return cfg


def cmd_run(args: argparse.Namespace) -> int:
    from src.core import FlowController, FlowStage
    from src.openroad_adapter import EDARunner, EDARunnerError
    from src.openroad_adapter.openroad_runner import SynthesisHandoffExecutor
    from src.qor import CrossStageFeedbackEngine
    from src.tuning import RuleBasedTuner
    from src.diagnostics.remediation import DiagnosticsModule
    from src.storage import RunLogger

    cfg = load_config(args.config)
    design = args.design
    seed = args.seed or cfg.get("flow", {}).get("seed", 42)
    work_dir = Path(cfg.get("storage", {}).get("runs_dir", "outputs/runs"))

    runner_kwargs = dict(cfg.get("eda", {}))
    eda = EDARunner(**{k: v for k, v in runner_kwargs.items()
                       if k in ("binary", "extra_args", "timeout_s", "env_extra")})

    controller = FlowController(
        design_name=design,
        work_dir=work_dir,
        config=cfg,
        seed=seed,
    )

    synth_exec = SynthesisHandoffExecutor()
    controller.register_executor(FlowStage.SYNTHESIS, synth_exec)
    for stage in [FlowStage.FLOORPLAN, FlowStage.PDN, FlowStage.GLOBAL_PLACE,
                   FlowStage.DETAIL_PLACE, FlowStage.CTS, FlowStage.GLOBAL_ROUTE,
                   FlowStage.DETAIL_ROUTE, FlowStage.FINISH]:
        controller.register_executor(stage, eda)

    if not args.no_tuning:
        controller.attach_tuner(RuleBasedTuner())

    feedback = CrossStageFeedbackEngine()
    controller.attach_feedback(feedback)

    if not args.no_diagnostics:
        controller.attach_diagnostics(DiagnosticsModule())

    log_dir = Path(cfg.get("storage", {}).get("runs_dir", "outputs/runs"))
    storage = RunLogger(log_dir)
    controller.attach_storage(storage)

    skip = [FlowStage(s) for s in (args.skip_stages or "").split(",") if s]
    state = controller.run(skip_stages=skip)

    import json, sys
    summary = controller.summary()
    print(json.dumps(summary, indent=2, default=str))
    return 0 if state.is_flow_complete() else 1


def cmd_sweep(args: argparse.Namespace) -> int:
    from src.benchmarks import IPSDLoader, DatasetNormalizer
    from src.benchmarks.collateral_validator import CollateralValidator
    cfg = load_config(args.config)
    loader = IPSDLoader(Path(args.manifest))
    norm = DatasetNormalizer()
    validator = CollateralValidator()
    benchmarks = loader.runnable()
    if not benchmarks:
        logging.warning("No runnable benchmarks found in manifest.")
        return 1
    results = []
    for bm in benchmarks:
        design_cfg = {**cfg, **norm.from_ipsd(bm)}
        val = validator.validate(bm.name, design_cfg)
        if not val.passed:
            logging.warning("Skipping %s: validation failed", bm.name)
            continue
        seeds = args.seeds or [cfg.get("flow", {}).get("seed", 42)]
        for seed in seeds:
            logging.info("Running sweep: design=%s seed=%d", bm.name, seed)
            _run_single(bm.name, design_cfg, seed, cfg)
    return 0


def cmd_ablation(args: argparse.Namespace) -> int:
    from src.benchmarks import IPSDLoader, DatasetNormalizer
    cfg = load_config(args.config)
    loader = IPSDLoader(Path(args.manifest or "configs/benchmarks/ipsd_manifest.yaml"))
    benchmarks = loader.runnable()[:2]
    ablations = cfg.get("reporting", {}).get("ablation", {}).get("configs", [])
    if not ablations:
        ablations = [{"name": "baseline", "modules": []}]
    for bm in benchmarks:
        norm = DatasetNormalizer()
        design_cfg = {**cfg, **norm.from_ipsd(bm)}
        for abl in ablations:
            tag = abl.get("name", "default")
            logging.info("Ablation: design=%s config=%s", bm.name, tag)
            abl_cfg = {**design_cfg, "config_tag": tag}
            _run_single(bm.name + f"_{tag}", abl_cfg,
                         cfg.get("flow", {}).get("seed", 42), abl_cfg)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from src.report import ExperimentSummary, MarkdownReporter, READMEUpdater
    from src.viz import QoRPlotter, CongestionPlotter, ComparisonPlotter

    cfg = load_config(args.config)
    runs_dir = Path(args.runs_dir or cfg.get("storage", {}).get("runs_dir", "outputs/runs"))
    figs_dir = Path(cfg.get("storage", {}).get("figures_dir", "outputs/figures"))
    report_path = Path(cfg.get("storage", {}).get("reports_dir", "outputs/reports")) / "REPORT.md"

    summ = ExperimentSummary(runs_dir)
    summ.load_all()
    rows = summ.flat_rows()
    rates = summ.success_rate_by_design()
    ablation = summ.ablation_table()

    qp = QoRPlotter(figs_dir)
    cp = CongestionPlotter(figs_dir)
    comp = ComparisonPlotter(figs_dir)

    saved_figs = []
    if rows:
        fig = qp.plot_wns_tns_bars(rows)
        if fig:
            saved_figs.append(fig)
        fig = cp.plot_congestion_vs_timing(rows)
        if fig:
            saved_figs.append(fig)
        fig = comp.plot_success_rate(rates)
        if fig:
            saved_figs.append(fig)
        if ablation:
            abl_dict = {r["config"]: r for r in ablation}
            fig = comp.plot_ablation(abl_dict, ["wns_mean", "tns_mean"])
            if fig:
                saved_figs.append(fig)
        fig = comp.plot_benchmark_summary_table(
            rows, ["design", "wns", "tns", "overflow", "drc_violations"]
        )
        if fig:
            saved_figs.append(fig)

    reporter = MarkdownReporter(report_path, figs_dir)
    reporter.generate(rows, ablation, rates)
    logging.info("REPORT.md generated: %s", report_path)

    if cfg.get("reporting", {}).get("auto_update_readme", True):
        updater = READMEUpdater(Path("README.md"))
        updater.update(rows, rates, saved_figs)
        logging.info("README.md updated")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from src.benchmarks import IPSDLoader
    from src.benchmarks.collateral_validator import CollateralValidator
    from src.benchmarks.dataset_normalizer import DatasetNormalizer
    loader = IPSDLoader(Path(args.manifest))
    validator = CollateralValidator()
    norm = DatasetNormalizer()
    any_fail = False
    for bm in loader.all():
        result = validator.validate(bm.name, norm.from_ipsd(bm))
        print(result.report())
        if not result.passed:
            any_fail = True
    return 1 if any_fail else 0


def _run_single(design_name: str, cfg: dict, seed: int, full_cfg: dict) -> None:
    from src.core import FlowController, FlowStage
    from src.openroad_adapter import EDARunner
    from src.openroad_adapter.openroad_runner import SynthesisHandoffExecutor
    from src.qor import CrossStageFeedbackEngine
    from src.tuning import RuleBasedTuner
    from src.diagnostics.remediation import DiagnosticsModule
    from src.storage import RunLogger

    work_dir = Path(full_cfg.get("storage", {}).get("runs_dir", "outputs/runs"))
    eda = EDARunner()
    ctrl = FlowController(design_name=design_name, work_dir=work_dir,
                           config=cfg, seed=seed)
    ctrl.register_executor(FlowStage.SYNTHESIS, SynthesisHandoffExecutor())
    for stage in [FlowStage.FLOORPLAN, FlowStage.PDN, FlowStage.GLOBAL_PLACE,
                   FlowStage.DETAIL_PLACE, FlowStage.CTS, FlowStage.GLOBAL_ROUTE,
                   FlowStage.DETAIL_ROUTE, FlowStage.FINISH]:
        ctrl.register_executor(stage, eda)
    ctrl.attach_tuner(RuleBasedTuner())
    ctrl.attach_feedback(CrossStageFeedbackEngine())
    ctrl.attach_diagnostics(DiagnosticsModule())
    ctrl.attach_storage(RunLogger(work_dir))
    ctrl.run()


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="pdflow",
        description="Next-Generation Physical Design Framework",
    )
    parser.add_argument("--log-level", default="INFO")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="Run flow for a single design")
    p_run.add_argument("--design", required=True)
    p_run.add_argument("--config")
    p_run.add_argument("--seed", type=int)
    p_run.add_argument("--skip-stages", dest="skip_stages", default="")
    p_run.add_argument("--no-tuning", action="store_true")
    p_run.add_argument("--no-diagnostics", action="store_true")

    p_sweep = sub.add_parser("sweep", help="Run sweep over benchmark manifest")
    p_sweep.add_argument("--manifest", default="configs/benchmarks/ipsd_manifest.yaml")
    p_sweep.add_argument("--config")
    p_sweep.add_argument("--seeds", nargs="+", type=int)

    p_abl = sub.add_parser("ablation", help="Run ablation study")
    p_abl.add_argument("--manifest")
    p_abl.add_argument("--config")

    p_rep = sub.add_parser("report", help="Generate reports and figures")
    p_rep.add_argument("--runs-dir")
    p_rep.add_argument("--config")

    p_val = sub.add_parser("validate", help="Validate benchmark collateral")
    p_val.add_argument("--manifest", default="configs/benchmarks/ipsd_manifest.yaml")

    args = parser.parse_args()
    setup_logging(args.log_level)

    dispatch = {
        "run":      cmd_run,
        "sweep":    cmd_sweep,
        "ablation": cmd_ablation,
        "report":   cmd_report,
        "validate": cmd_validate,
    }
    fn = dispatch.get(args.command)
    if fn is None:
        parser.print_help()
        return 1
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
