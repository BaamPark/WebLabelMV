#!/usr/bin/env bash

set -euo pipefail

# Edit these values in this file instead of exporting env vars in your shell.
export SECRET_KEY="changeme-in-prod"
export CHATBOT_PROVIDER="ollama"
export CHATBOT_BASE_URL="http://host.docker.internal:11434"
export CHATBOT_REQUEST_PATH="/api/chat"
export CHATBOT_API_KEY=""
export CHATBOT_MODEL="qwen3.5:9b"
export CHATBOT_OLLAMA_THINK="false"
export CHATBOT_TIMEOUT_SECONDS="300"
export CHATBOT_MAX_TOKENS="1024"
export CHATBOT_MAX_IMAGE_BYTES="10485760"
# Set to "true" to log both the grounded first agent call and the post-tool follow-up call.
export AGENT_INPUT_LOGGING="true"

docker compose up --build "$@"
