"""Settings, read once from the environment (and the project-root .env file)."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
SAMPLES_DIR = ROOT / "samples"
EVAL_DIR = ROOT / "eval"
FRONTEND_DIST = ROOT / "frontend" / "dist"

# gemini | anthropic | openai | none
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
# Tried in order when the main model is busy (503) or rate-limited (429).
GEMINI_FALLBACK_MODELS = [m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash,gemini-flash-latest").split(",") if m.strip()]
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")

USE_EMBEDDINGS = os.getenv("USE_EMBEDDINGS", "1") == "1"
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "15"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "40"))
RATE_LIMIT_PER_HOUR = int(os.getenv("RATE_LIMIT_PER_HOUR", "0"))  # per visitor; 0 = off
# Uploads per hour across all visitors (a visitor's IP can be faked, so this caps the total). 0 = no cap.
UPLOADS_PER_HOUR = int(os.getenv("UPLOADS_PER_HOUR", "0"))
# Uploaded documents kept in memory at once; older ones are reloaded from disk when asked about.
MAX_CACHED_UPLOADS = int(os.getenv("MAX_CACHED_UPLOADS", "20"))
# Seconds an upload waits for the one before it to finish reading before it is turned away.
UPLOAD_QUEUE_WAIT_S = int(os.getenv("UPLOAD_QUEUE_WAIT_S", "30"))
# Model calls per UTC day across all visitors; past it, answers fall back to no-key mode. 0 = no cap.
DAILY_LLM_LIMIT = int(os.getenv("DAILY_LLM_LIMIT", "0"))
# Uploaded PDFs are deleted after this many hours (samples are kept). 0 = keep them.
UPLOAD_TTL_HOURS = float(os.getenv("UPLOAD_TTL_HOURS", "0"))
# OCR for uploaded scans peaks around 1 GB of memory; 0 skips scanned pages of uploads (samples are still OCR'd).
OCR_UPLOADS = os.getenv("OCR_UPLOADS", "1") == "1"

TOP_K = int(os.getenv("TOP_K", "6"))
LLM_TIMEOUT_S = int(os.getenv("LLM_TIMEOUT_S", "45"))
