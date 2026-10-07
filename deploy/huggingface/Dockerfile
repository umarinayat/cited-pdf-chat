# Hugging Face Space: builds the app straight from the GitHub repository, the same way as ../../Dockerfile
# (keep the two in sync). The source archive is re-downloaded on every build, so Settings -> "Factory rebuild"
# deploys the latest commit on main.

FROM node:22-slim AS src
ADD https://github.com/umarinayat/cited-pdf-chat/archive/refs/heads/main.tar.gz /tmp/src.tar.gz
RUN mkdir /src && tar -xzf /tmp/src.tar.gz -C /src --strip-components=1

FROM node:22-slim AS web
WORKDIR /web
COPY --from=src /src/frontend/ ./
RUN npm ci --no-audit --no-fund && npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HUB_DISABLE_SYMLINKS_WARNING=1 \
    FASTEMBED_CACHE_PATH=/app/.cache/fastembed
# OpenCV (used by the OCR engine) needs these at runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=src /src/backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY --from=src /src/backend/ backend/
COPY --from=src /src/samples/ samples/
COPY --from=src /src/eval/ eval/
COPY --from=web /web/dist frontend/dist
# Pre-build the sample documents (OCR + embeddings) so the first visitor doesn't wait.
RUN cd backend && LLM_PROVIDER=none python -c "from app import store; store.ensure_samples()"
# Spaces run containers as uid 1000
RUN useradd --create-home --uid 1000 app && chown -R app /app
USER app
# Public-demo limits; Space variables override these.
ENV PORT=8000 RATE_LIMIT_PER_HOUR=30 DAILY_LLM_LIMIT=300 UPLOAD_TTL_HOURS=24
EXPOSE 8000
CMD ["sh", "-c", "cd backend && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
