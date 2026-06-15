# syntax=docker/dockerfile:1
#
# Image for the FastAPI agent surface ONLY. It contains NO model artifacts —
# models are served by a separate llama.cpp process/container and mounted as a
# volume (see docker-compose.yml). This mirrors the init-container pattern:
# code and models have different lifecycles and sizes.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install runtime deps first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the platform code (core + use-cases + transport). No models, no secrets.
COPY core ./core
COPY usecases ./usecases
COPY app ./app

# Non-root user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# Single worker on purpose — horizontal scale is the orchestrator's job (HPA),
# never in-process workers (project invariant).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
