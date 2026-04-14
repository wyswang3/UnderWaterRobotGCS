#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

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
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  echo "[ERR] python interpreter not found"
  exit 1
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo ""
echo "============================================"
echo " UnderWaterRobotGCS - GUI Launcher"
echo "============================================"
echo ""
echo "[INFO] Project root: ${ROOT}"
echo "[INFO] Python: ${PYTHON_BIN}"
echo "[INFO] Python version: $("${PYTHON_BIN}" --version 2>&1)"
echo ""

# GUI is a read-only observer; default to an ephemeral bind port so it can run
# alongside the TUI without fighting over the fixed telemetry port.
: "${UROGCS_GUI_BIND_PORT:=0}"
export UROGCS_GUI_BIND_PORT

"$PYTHON_BIN" -m urogcs.tools.preflight_check --bind-port "$UROGCS_GUI_BIND_PORT"
if [[ ${PRECHECK_ONLY} -eq 1 ]]; then
  echo ""
  echo "[INFO] Preflight only mode complete"
  exit 0
fi

exec "$PYTHON_BIN" -m urogcs.app.gui_main "${APP_ARGS[@]}"
