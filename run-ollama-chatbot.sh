#!/usr/bin/env bash

set -euo pipefail

# Edit these values in this file instead of exporting env vars in your shell.
export SECRET_KEY="changeme-in-prod"
export CHATBOT_PROVIDER="ollama"
export CHATBOT_BASE_URL="http://host.docker.internal:11434"
export CHATBOT_REQUEST_PATH="/api/generate"
export CHATBOT_API_KEY=""
export CHATBOT_MODEL="qwen3-vl:8b-instruct"
export CHATBOT_TIMEOUT_SECONDS="180"
export CHATBOT_MAX_TOKENS="1024"
export CHATBOT_MAX_IMAGE_BYTES="10485760"

docker compose up --build "$@"
