# LabelMV

LabelMV is a web-based video annotation tool with a React frontend, a Flask backend, and MongoDB for persistence.

## Run with Docker

This repository includes a Docker setup that packages the frontend, backend, and MongoDB, and wires them together with docker-compose.

- Prerequisites: Docker and Docker Compose

### 1) Start the stack

- Build and start in the background:
  
  - `docker compose up --build -d`

- Open the app:
  
  - http://localhost:3001

- Backend API (direct):
  
  - http://localhost:56250

- MongoDB (for local tools):
  
  - mongodb://localhost:27017

### 2) Provide videos

- The compose file mounts the host `./videos` folder into the backend container at `/app/videos` (read-only).
- Copy or link your video files into the local `videos/` directory.
- The app automatically uses `/app/videos` for projects; no manual path entry is needed.

### 3) Environment variables

- Secret key:
  
  - `SECRET_KEY=your_secret docker compose up -d`

- MongoDB URI (defaults to the internal service):
  
  - `MONGO_URI=mongodb://mongo:27017/labelmv` (set in compose for the backend)

- Chatbot proxy and local HF model server:
  
  - `CHATBOT_PROVIDER=hf_server`
  - `CHATBOT_BASE_URL=http://host.docker.internal:8000`
  - `CHATBOT_REQUEST_PATH=/generate`
  - `CHATBOT_API_KEY=` (optional)
  - `CHATBOT_MODEL=Qwen/Qwen3-VL-2B-Instruct`
  - `CHATBOT_TIMEOUT_SECONDS=180`
  - `CHATBOT_MAX_TOKENS=1024`
  - `CHATBOT_MAX_IMAGE_BYTES=10485760`

### 4) Stop and clean

- Stop services: `docker compose down`
- Remove Mongo data volume: `docker compose down -v`

## How it’s wired

- Frontend (React) is built and served by Nginx on port 3001.
- Nginx proxies `/api/*` and `/videos` to the backend service at `backend:56250`.
- Backend (Flask + Gunicorn) listens on port 56250 and connects to Mongo.
- MongoDB uses a named volume `mongo-data` for persistence.

## Development (optional)

You can still run each part locally outside Docker:

- Backend (from `labelmv-backend/`):
  
  - Create a venv, install `requirements.txt`, run `FLASK_ENV=development python app.py`.

- Frontend (from `labelmv-frontend/`):
  
  - `npm install` then `npm start` (dev server on 3001). The CRA proxy in `package.json` points to `http://localhost:56250` for API.

## Multimodal Chatbot

This milestone adds only a user-facing multimodal chatbot. It does not add agentic auto-annotation or gating.

### Setup

- The app backend now calls a separate model server by `base_url`.
- The HF model server runs on the host machine, not in Docker.
- Default local model server:
  
  - `Qwen/Qwen3-VL-2B-Instruct`

- Start the host model server first:
  
  - `./hf-model-server/start_local_hf_model.sh`

- Then start the app stack:
  
  - `./run-local-chatbot.sh -d`

- Sign in, open a project, and use the floating `Ask AI` button on the annotation page.

### How it works

- Frontend sends `multipart/form-data` with:
  
  - `text`: prompt text
  - `image`: optional single uploaded image

- App backend route:
  
  - `POST /api/chatbot`

- App backend forwards that request to:
  
  - `${CHATBOT_BASE_URL}${CHATBOT_REQUEST_PATH}`

- Supported backend providers in the app proxy:
  
  - `hf_server` for the included host-run Hugging Face `transformers` server
  - `ollama` for Ollama's native HTTP API

- Default local model server route:
  
  - `POST http://localhost:8000/generate`

- Default model server:
  
  - `Qwen/Qwen3-VL-2B-Instruct`

- The local model server uses `transformers` directly. The Qwen model card currently advises installing the latest `transformers` from source for Qwen3-VL support:
  
  - https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct
  - https://huggingface.co/docs/transformers/model_doc/qwen3_vl

- To point the app at Ollama later, change only the app-side settings:
  
  - `CHATBOT_PROVIDER=ollama`
  - `CHATBOT_BASE_URL=http://host.docker.internal:11434`
  - `CHATBOT_REQUEST_PATH=/api/generate`
  - `CHATBOT_MODEL=<your-ollama-vision-model>`

- Helper scripts for Ollama:
  
  - `./start-ollama-model.sh`
  - `./run-ollama-chatbot.sh -d`

- Ollama API reference used for compatibility:
  
  - https://docs.ollama.com/api/introduction
  - https://docs.ollama.com/api/generate

### Quick test example

With a valid bearer token and local image:

```bash
curl -X POST http://localhost:56250/api/chatbot \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -F "text=Describe the important objects in this image." \
  -F "image=@/absolute/path/to/example.jpg"
```

Directly against the host model server:

```bash
python - <<'PY'
import base64
import json
from pathlib import Path
import requests

image_path = Path("/absolute/path/to/example.jpg")
payload = {
    "model": "Qwen/Qwen3-VL-2B-Instruct",
    "text": "Describe the important objects in this image.",
    "image_base64": base64.b64encode(image_path.read_bytes()).decode("utf-8"),
    "image_name": image_path.name,
    "max_new_tokens": 256,
}

response = requests.post("http://localhost:8000/generate", json=payload, timeout=300)
print(response.status_code)
print(json.dumps(response.json(), indent=2))
PY
```

## Files of interest

- `docker-compose.yml` – Orchestrates `frontend`, `backend`, and `mongo` services.
- `labelmv-backend/Dockerfile` – Flask backend container (Gunicorn runtime).
- `labelmv-frontend/Dockerfile` – React build + Nginx runtime.
- `labelmv-frontend/nginx.conf` – Proxies API and `/videos` to backend.
- `labelmv-backend/app.py` – Reads `MONGO_URI` and `SECRET_KEY` from env.
- `hf-model-server/app.py` – Host-run local Hugging Face model server.
- `hf-model-server/start_local_hf_model.sh` – Host startup script for the local model server.
- `start-ollama-model.sh` – Host helper to start Ollama and pull a vision model.
- `run-ollama-chatbot.sh` – App stack launcher configured for Ollama.
