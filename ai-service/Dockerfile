# ─── Base: CPU only. Every feature must work without a GPU. ───
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY pyproject.toml ./
RUN pip install -U pip && pip install -e ".[ui]"

COPY app ./app
COPY config ./config
COPY ui ./ui

# ملحوظة: app/main.py Flask app (WSGI) مش FastAPI/ASGI - uvicorn ميعرفش
# يشغّلها. لازم gunicorn (WSGI server) بدل uvicorn في production.
RUN pip install "gunicorn>=23.0"

EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD curl -fsS http://localhost:5000/api/v1/health || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "90", "app.main:app"]


# ─── Optional GPU / Hugging Face variant ───
# Build with:  docker build --target hf -t amit-ai-service:hf .
FROM base AS hf
RUN pip install -e ".[hf]"