#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

PRECHECK_ONLY=0
if [[ "${1:-}" == "--preflight-only" ]]; then
  PRECHECK_ONLY=1
  shift
fi

if [[ $# -ne 0 ]]; then
  echo "[ERR] Unsupported arguments: $*"
  echo "[INFO] Usage: scripts/run_tui.sh [--preflight-only]"
  exit 2
fi

if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "[ERR] Python not found. Install Python 3.10+ first."
  exit 2
fi

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

echo ""
echo "============================================"
echo " UnderWaterRobotGCS - TUI Launcher"
echo "============================================"
echo ""
echo "[INFO] Project root: ${ROOT_DIR}"
echo "[INFO] Python: ${PYTHON_BIN}"
echo ""

"${PYTHON_BIN}" -m urogcs.tools.preflight_check

if [[ ${PRECHECK_ONLY} -eq 1 ]]; then
  echo ""
  echo "[INFO] Preflight only mode complete"
  exit 0
fi

echo ""
echo "[INFO] Starting TUI"
echo "[INFO] Press Ctrl+C to exit"
echo ""
exec "${PYTHON_BIN}" -m urogcs.app.tui.tui_main
