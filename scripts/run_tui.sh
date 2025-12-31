#!/usr/bin/env bash
set -euo pipefail

echo ""
echo "============================================"
echo " UnderWaterRobotGCS - TUI Controller"
echo "============================================"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

echo "[INFO] Project root: ${ROOT_DIR}"
echo "[INFO] Starting TUI (keyboard control)..."
echo ""

if [[ -f ".venv/bin/activate" ]]; then
  echo "[INFO] Activating virtual environment (.venv)"
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
else
  echo "[WARN] No .venv found, using system Python"
fi

echo ""
echo "[INFO] Press Ctrl+C to exit"
echo ""

python -m urogcs.app.tui_main

echo ""
echo "[INFO] TUI exited"
