#!/usr/bin/env bash

set -euo pipefail

# Edit these values in this file instead of exporting env vars in your shell.
export SECRET_KEY="changeme-in-prod"
export CHATBOT_PROVIDER="openrouter"
export CHATBOT_BASE_URL="https://openrouter.ai/api/v1"
export CHATBOT_REQUEST_PATH="/chat/completions"
export CHATBOT_API_KEY=""
export CHATBOT_SITE_URL=""
export CHATBOT_SITE_TITLE="WebLabelMV"
export CHATBOT_MODEL="qwen/qwen3.5-27b"
export CHATBOT_TIMEOUT_SECONDS="300"
export CHATBOT_MAX_TOKENS="1024"
export CHATBOT_SEED="42"
export CHATBOT_TEMPERATURE="0.8"
export CHATBOT_MAX_IMAGE_BYTES="10485760"
export ML_BACKEND_URL="http://host.docker.internal:8001/detect"
export AGENT_INPUT_IMAGE_DUMP="true"
export AGENT_INPUT_IMAGE_DUMP_DIR="/app/tmp"
# Set to "true" to log both the grounded first agent call and the post-tool follow-up call.
export AGENT_INPUT_LOGGING="true"

docker compose up --build "$@"
