#!/usr/bin/env bash
set -euo pipefail

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "[ERR] please source this file instead of executing it"
  echo "[INFO] usage: source scripts/enter_gcs_env.sh"
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

select_python() {
  if [[ -n "${UROGCS_PYTHON_BIN:-}" ]]; then
    if [[ ! -x "${UROGCS_PYTHON_BIN}" ]]; then
      echo "[ERR] UROGCS_PYTHON_BIN is not executable: ${UROGCS_PYTHON_BIN}"
      return 1
    fi
    return 0
  fi
  if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
    UROGCS_PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    UROGCS_PYTHON_BIN="$(command -v python3)"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    UROGCS_PYTHON_BIN="$(command -v python)"
    return 0
  fi
  echo "[ERR] python interpreter not found"
  return 1
}

select_python
export UROGCS_PYTHON_BIN
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

if [[ -f "${ROOT_DIR}/.venv/bin/activate" && "${UROGCS_PYTHON_BIN}" == "${ROOT_DIR}/.venv/bin/python" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.venv/bin/activate"
fi

echo "[INFO] GCS root: ${ROOT_DIR}"
echo "[INFO] UROGCS_PYTHON_BIN: ${UROGCS_PYTHON_BIN}"
echo "[INFO] Python version: $("${UROGCS_PYTHON_BIN}" --version 2>&1)"
