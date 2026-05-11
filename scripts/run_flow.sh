#!/usr/bin/env bash
# run_flow.sh — execute the full physical design flow for one design
set -euo pipefail

DESIGN=${1:-gcd}
CONFIG=${2:-configs/base.yaml}
SEED=${3:-42}

echo "=== Physical Design Flow ==="
echo "Design : ${DESIGN}"
echo "Config : ${CONFIG}"
echo "Seed   : ${SEED}"
echo ""

python main.py run \
    --design "${DESIGN}" \
    --config "${CONFIG}" \
    --seed   "${SEED}"
