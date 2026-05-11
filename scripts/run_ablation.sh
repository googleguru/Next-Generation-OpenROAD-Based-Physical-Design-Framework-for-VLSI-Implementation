#!/usr/bin/env bash
# run_ablation.sh — run ablation study across module configurations
set -euo pipefail

MANIFEST=${1:-configs/benchmarks/ipsd_manifest.yaml}
CONFIG=${2:-configs/base.yaml}

echo "=== Ablation Study ==="
echo "Manifest : ${MANIFEST}"
echo "Config   : ${CONFIG}"
echo ""

python main.py ablation \
    --manifest "${MANIFEST}" \
    --config   "${CONFIG}"
