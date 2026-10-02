#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
umask 077
if [[ ! -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  "${PYTHON_BIN}" -c 'import sys; sys.exit("Python 3.11 or newer is required") if sys.version_info < (3, 11) else None'
  "${PYTHON_BIN}" -m venv "${ROOT_DIR}/.venv"
fi
"${ROOT_DIR}/.venv/bin/python" -m pip install -r "${ROOT_DIR}/requirements.txt"
exec "${ROOT_DIR}/.venv/bin/python" "${ROOT_DIR}/bot.py" --setup "$@"
