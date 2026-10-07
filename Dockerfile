# One container: the FastAPI backend serves the API and the built React app.
#   docker build -t cited-pdf-chat .
#   docker run -p 8000:8000 -e GEMINI_API_KEY=... cited-pdf-chat

FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HUB_DISABLE_SYMLINKS_WARNING=1 \
    FASTEMBED_CACHE_PATH=/app/.cache/fastembed
# OpenCV (used by the OCR engine) needs these at runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY samples/ samples/
COPY eval/ eval/
COPY --from=web /web/dist frontend/dist
# Pre-build the sample documents (OCR + embeddings) so the first visitor doesn't wait.
RUN cd backend && LLM_PROVIDER=none python -c "from app import store; store.ensure_samples()"
# Run unprivileged (Hugging Face Spaces runs containers as uid 1000)
RUN useradd --create-home --uid 1000 app && chown -R app /app
USER app
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "cd backend && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
