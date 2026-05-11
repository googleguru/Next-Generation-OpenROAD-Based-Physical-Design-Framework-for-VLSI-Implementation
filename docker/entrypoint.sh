#!/usr/bin/env bash
# entrypoint.sh — Docker container entry point
set -euo pipefail

cd /workspace

# Honour EDA_BINARY env override
if [[ -n "${EDA_BINARY:-}" ]]; then
    export PATH="${EDA_BINARY%/*}:${PATH}"
fi

echo "=== Physical Design Framework ==="
echo "Python : $(python3 --version)"
echo "Yosys  : $(yosys --version 2>/dev/null || echo 'not found')"
echo "EDA    : $(command -v openroad 2>/dev/null || echo 'not found (set EDA_BINARY)')"
echo ""

exec python3 main.py "$@"
