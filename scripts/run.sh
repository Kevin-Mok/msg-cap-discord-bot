#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
umask 077
if [[ ! -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  echo 'Virtual environment missing. Run ./scripts/setup.sh first.' >&2
  exit 1
fi
exec "${ROOT_DIR}/.venv/bin/python" "${ROOT_DIR}/bot.py" "$@"
