#!/usr/bin/env bash

set -euo pipefail

# Edit these values in this file instead of exporting env vars in your shell.
export SECRET_KEY="changeme-in-prod"
export CHATBOT_PROVIDER="google_genai"
export CHATBOT_BASE_URL="https://generativelanguage.googleapis.com"
export CHATBOT_REQUEST_PATH="/v1beta/models/{model}:generateContent"
export CHATBOT_API_KEY="AIzaSyCntrG4Dtxg2vmRUqRWBpj8c2Fp62-haE4"
export CHATBOT_MODEL="gemini-3-flash-preview"
export CHATBOT_TIMEOUT_SECONDS="300"
export CHATBOT_MAX_TOKENS="1024"
export CHATBOT_MAX_IMAGE_BYTES="10485760"
export AGENT_INPUT_LOGGING="true"

docker compose up --build "$@"
