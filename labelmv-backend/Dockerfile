FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for opencv
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 libsm6 libxrender1 libxext6 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./

# Env defaults (overridden by compose)
ENV HOST=0.0.0.0 \
    PORT=56250 \
    MONGO_URI=mongodb://mongo:27017/labelmv \
    SECRET_KEY=changeme-in-prod

EXPOSE 56250

# Run with gunicorn for production
CMD ["gunicorn", "-w", "3", "-b", "0.0.0.0:56250", "app:app"]

