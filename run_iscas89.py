#!/usr/bin/env python3
"""
Run the complete ISCAS-89 physical design flow for all sequential benchmark circuits.

Usage:
    python run_iscas89.py
    python run_iscas89.py --circuits s27 s298
    python run_iscas89.py --bench-dir benchmarks/iscas/sequential
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).parent / "src"))

from iscas89.flow_runner import ISCAS89FlowRunner

_DEFAULT_CIRCUITS = ["s27", "s298", "s344", "s386", "s526"]
_BENCH_DIR = Path("benchmarks/iscas/sequential")
_FIGURES_DIR = Path("outputs/figures/iscas89")
_GDS_DIR = Path("outputs/gds")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ISCAS-89 complete PD flow: partition→floorplan→place→STA→layout→compact→RC→GDS"
    )
    parser.add_argument(
        "--circuits", nargs="+", default=_DEFAULT_CIRCUITS,
        help="Circuit names to process (default: all 5 sequential)"
    )
    parser.add_argument(
        "--bench-dir", type=Path, default=_BENCH_DIR,
        help="Directory containing .bench files"
    )
    parser.add_argument(
        "--figures-dir", type=Path, default=_FIGURES_DIR,
        help="Output directory for figures"
    )
    parser.add_argument(
        "--gds-dir", type=Path, default=_GDS_DIR,
        help="Output directory for GDS II files"
    )
    parser.add_argument(
        "--partitions", type=int, default=2,
        help="Number of partitions for FM partitioner"
    )
    parser.add_argument(
        "--utilization", type=float, default=0.65,
        help="Target floorplan utilization (0-1)"
    )
    args = parser.parse_args()

    bench_paths = []
    for name in args.circuits:
        p = args.bench_dir / f"{name}.bench"
        if not p.exists():
            print(f"[WARNING] bench file not found: {p}")
        else:
            bench_paths.append(p)

    if not bench_paths:
        print("[ERROR] No valid .bench files found. Exiting.")
        sys.exit(1)

    print(f"\nISCAS-89 Physical Design Flow")
    print(f"Circuits : {[p.stem for p in bench_paths]}")
    print(f"Figures  : {args.figures_dir}")
    print(f"GDS      : {args.gds_dir}")
    print(f"Partitions: {args.partitions}  Utilization: {args.utilization:.0%}")

    runner = ISCAS89FlowRunner(
        figures_dir=args.figures_dir,
        gds_dir=args.gds_dir,
        num_partitions=args.partitions,
        target_utilization=args.utilization,
    )

    t_start = time.perf_counter()
    results, summary_path = runner.run_all(bench_paths)
    elapsed = time.perf_counter() - t_start

    print(f"\n{'='*60}")
    print(f" Flow complete in {elapsed:.1f}s")
    print(f"{'='*60}")
    for r in results:
        errors = list(r.errors.keys())
        figs = len(r.figure_paths)
        gds = r.gds_path.name if r.gds_path else "MISSING"
        status = "OK" if not errors else f"WARN({','.join(errors)})"
        print(f"  {r.circuit_name:8s}  figs={figs}  gds={gds}  [{status}]")

    print(f"\n  Summary JSON: {summary_path}")
    print(f"  Figures dir : {args.figures_dir}")
    print(f"  GDS dir     : {args.gds_dir}")


if __name__ == "__main__":
    main()
