#!/usr/bin/env bash

set -euo pipefail

# Edit these values in this file instead of exporting env vars in your shell.
export SECRET_KEY="changeme-in-prod"
export CHATBOT_PROVIDER="google_genai"
export CHATBOT_BASE_URL="https://generativelanguage.googleapis.com"
export CHATBOT_REQUEST_PATH="/v1beta/models/{model}:generateContents"
export CHATBOT_API_KEY=""
export CHATBOT_MODEL="gemini-3-flash-preview"
export CHATBOT_TIMEOUT_SECONDS="300"
export CHATBOT_MAX_TOKENS="2048"
export CHATBOT_MAX_IMAGE_BYTES="10485760"
export ML_BACKEND_URL="http://host.docker.internal:8001/detect"
export AGENT_MAX_TOOL_STEPS="4"
# Set to "true" to log both the grounded first agent call and the post-tool follow-up call.
export AGENT_INPUT_LOGGING="false"

docker compose up --build "$@"
