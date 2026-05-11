#!/usr/bin/env bash
# make_report.sh — aggregate results, generate all figures, update README + REPORT.md
set -euo pipefail

RUNS_DIR=${1:-outputs/runs}
CONFIG=${2:-configs/base.yaml}

echo "=== Report Generation ==="
echo "Runs dir : ${RUNS_DIR}"
echo ""

python main.py report \
    --runs-dir "${RUNS_DIR}" \
    --config   "${CONFIG}"

echo ""
echo "Done. See outputs/reports/REPORT.md and outputs/figures/"
