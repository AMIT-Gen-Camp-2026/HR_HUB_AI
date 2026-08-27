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

EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD curl -fsS http://localhost:8100/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]


# ─── Optional GPU / Hugging Face variant ───
# Build with:  docker build --target hf -t amit-ai-service:hf .
FROM base AS hf
RUN pip install -e ".[hf]"
