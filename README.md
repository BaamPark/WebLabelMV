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

## Files of interest

- `docker-compose.yml` – Orchestrates `frontend`, `backend`, and `mongo` services.
- `labelmv-backend/Dockerfile` – Flask backend container (Gunicorn runtime).
- `labelmv-frontend/Dockerfile` – React build + Nginx runtime.
- `labelmv-frontend/nginx.conf` – Proxies API and `/videos` to backend.
- `labelmv-backend/app.py` – Reads `MONGO_URI` and `SECRET_KEY` from env.
