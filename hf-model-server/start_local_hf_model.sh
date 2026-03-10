#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Edit these values locally instead of exporting env vars in your shell.
export MODEL_ID="Qwen/Qwen3-VL-2B-Instruct"
export MODEL_DEVICE="cuda"
export MODEL_DTYPE="bfloat16"
export MAX_IMAGE_BYTES="10485760"
export DEFAULT_MAX_NEW_TOKENS="1024"
export MODEL_SERVER_HOST="0.0.0.0"
export MODEL_SERVER_PORT="8000"

if [[ ! -d "${SCRIPT_DIR}/.venv" ]]; then
  python3 -m venv "${SCRIPT_DIR}/.venv"
fi

source "${SCRIPT_DIR}/.venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "${SCRIPT_DIR}/requirements-host.txt"

exec python "${SCRIPT_DIR}/app.py"
