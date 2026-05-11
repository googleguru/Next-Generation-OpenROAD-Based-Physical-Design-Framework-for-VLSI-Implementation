#!/usr/bin/env bash
# run_sweep.sh — run all benchmarks in a manifest, optionally over multiple seeds
set -euo pipefail

MANIFEST=${1:-configs/benchmarks/ipsd_manifest.yaml}
SEEDS=${2:-"42 123 7"}
CONFIG=${3:-configs/base.yaml}

echo "=== Benchmark Sweep ==="
echo "Manifest : ${MANIFEST}"
echo "Seeds    : ${SEEDS}"
echo ""

python main.py sweep \
    --manifest "${MANIFEST}" \
    --config   "${CONFIG}" \
    --seeds    ${SEEDS}
