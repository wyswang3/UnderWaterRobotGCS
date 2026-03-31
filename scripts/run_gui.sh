#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
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

# GUI is a read-only observer; default to an ephemeral bind port so it can run
# alongside the TUI without fighting over the fixed telemetry port.
: "${UROGCS_GUI_BIND_PORT:=0}"
export UROGCS_GUI_BIND_PORT

"$PYTHON_BIN" -m urogcs.tools.preflight_check --bind-port "$UROGCS_GUI_BIND_PORT"
exec "$PYTHON_BIN" -m urogcs.app.gui_main "$@"
