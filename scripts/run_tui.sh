#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

PRECHECK_ONLY=0
declare -a APP_ARGS=()
while [[ $# -gt 0 ]]; do
  case "${1}" in
    --preflight-only)
      PRECHECK_ONLY=1
      shift
      ;;
    *)
      APP_ARGS+=("${1}")
      shift
      ;;
  esac
done

if [[ -n "${UROGCS_PYTHON_BIN:-}" ]]; then
  if [[ ! -x "${UROGCS_PYTHON_BIN}" ]]; then
    echo "[ERR] UROGCS_PYTHON_BIN is not executable: ${UROGCS_PYTHON_BIN}"
    exit 2
  fi
  PYTHON_BIN="${UROGCS_PYTHON_BIN}"
elif [[ -x ".venv/bin/python" ]]; then
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
echo "[INFO] Python version: $("${PYTHON_BIN}" --version 2>&1)"
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
exec "${PYTHON_BIN}" -m urogcs.app.tui.tui_main "${APP_ARGS[@]}"
