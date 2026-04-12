#!/usr/bin/env bash

set -euo pipefail

# Edit these values in this file instead of exporting env vars in your shell.
export SECRET_KEY="changeme-in-prod"
export CHATBOT_PROVIDER="openai"
export CHATBOT_BASE_URL="https://api.openai.com"
export CHATBOT_REQUEST_PATH="/v1/responses"
export CHATBOT_API_KEY=""
export CHATBOT_MODEL="gpt-5.4-mini"
export CHATBOT_TIMEOUT_SECONDS="300"
export CHATBOT_MAX_TOKENS="1024"
export CHATBOT_SEED="42"
export CHATBOT_TEMPERATURE="0.8"
export CHATBOT_MAX_IMAGE_BYTES="10485760"
export ML_BACKEND_URL="http://host.docker.internal:8001/detect"
# Set to "true" to log both the grounded first agent call and the post-tool follow-up call.
export AGENT_INPUT_LOGGING="true"

docker compose up --build "$@"
