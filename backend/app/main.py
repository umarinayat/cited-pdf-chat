"""HTTP API + the built web app, served from one process."""

from __future__ import annotations

import json
import re
import tempfile
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

import pymupdf
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, llm, store
from .answer import answer_question
from .ingest import needs_ocr
from .retrieval import embedder


def _prune_forever() -> None:
    while True:
        store.prune_uploads(config.UPLOAD_TTL_HOURS)
        time.sleep(600)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Build the sample documents in the background so the server answers immediately.
    threading.Thread(target=store.ensure_samples, daemon=True).start()
    if config.UPLOAD_TTL_HOURS > 0:
        threading.Thread(target=_prune_forever, daemon=True).start()
    yield


# No auto-generated API docs on a public demo: /docs, /redoc and /openapi.json are switched off.
app = FastAPI(title="Cited PDF Chat", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

# ---- request size and security headers

MAX_JSON_BYTES = 16 * 1024
_UPLOAD_PATH = "/api/docs"


@app.middleware("http")
async def guard(request: Request, call_next):
    # Turn big bodies away before they are read or saved to disk.
    if request.method == "POST":
        limit = config.MAX_UPLOAD_MB * 1024 * 1024 + 64 * 1024 if request.url.path == _UPLOAD_PATH else MAX_JSON_BYTES
        length = request.headers.get("content-length")
        if length is None:
            return JSONResponse({"detail": "Content-Length is required."}, status_code=411)
        if not length.isdigit() or int(length) > limit:
            return JSONResponse({"detail": f"PDFs up to {config.MAX_UPLOAD_MB} MB, please." if request.url.path == _UPLOAD_PATH
                                 else "Request too large."}, status_code=413)
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/api/"):
        h.setdefault("Cache-Control", "no-store")
    return response


# ---- rate limits

_hits: dict[str, deque] = defaultdict(deque)
_uploads: deque = deque()
_hits_lock = threading.Lock()
_ingest_lock = threading.Lock()


def client_ip(request: Request) -> str:
    """The visitor's IP. Render sits behind Cloudflare, which sets True-Client-IP / CF-Connecting-IP itself.
    X-Forwarded-For is only a fallback: its first entry comes from the visitor and can be made up, which is
    why uploads also have a cap across all visitors (UPLOADS_PER_HOUR) and model calls a daily cap."""
    for name in ("true-client-ip", "cf-connecting-ip"):
        value = request.headers.get(name, "").strip()
        if value:
            return value[:64]
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded[:64] or (request.client.host if request.client else "?")


def _over(q: deque, limit: int, now: float) -> bool:
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def _rate_limited(request: Request) -> bool:
    if config.RATE_LIMIT_PER_HOUR <= 0:
        return False
    with _hits_lock:
        if len(_hits) > 50_000:  # forget idle visitors so made-up IPs can't grow this forever
            for key in [k for k, q in _hits.items() if not q or time.time() - q[-1] > 3600]:
                del _hits[key]
        return _over(_hits[client_ip(request)], config.RATE_LIMIT_PER_HOUR, time.time())


def _uploads_full() -> bool:
    if config.UPLOADS_PER_HOUR <= 0:
        return False
    with _hits_lock:
        return _over(_uploads, config.UPLOADS_PER_HOUR, time.time())


def _doc_or_404(doc_id: str) -> store.Doc:
    doc = store.get(doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    return doc


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health():
    act = llm.active()
    return {
        "mode": "llm" if act else "extractive",
        "provider": act[0] if act else None,
        "model": act[1] if act else None,
        "embeddings": embedder.ok,
        "max_upload_mb": config.MAX_UPLOAD_MB,
        "max_pages": config.MAX_PAGES,
        "upload_ttl_hours": config.UPLOAD_TTL_HOURS,
        "ocr_uploads": config.OCR_UPLOADS,
    }


@app.get("/api/samples")
def samples():
    return store.samples()


@app.get("/api/docs/{doc_id}")
def doc_meta(doc_id: str):
    return _doc_or_404(doc_id).meta


@app.get("/api/docs/{doc_id}/file")
def doc_file(doc_id: str):
    doc = _doc_or_404(doc_id)
    # The viewer fetches this with PDF.js. Opened directly, an uploaded PDF downloads instead of rendering on
    # this site, and the sandbox stops any script in it from running with this site's origin.
    return FileResponse(doc.pdf, media_type="application/pdf", headers={
        "Cache-Control": "private, max-age=3600",
        "Content-Disposition": 'attachment; filename="document.pdf"',
        "Content-Security-Policy": "sandbox",
    })


@app.get("/api/docs/{doc_id}/numbers")
def doc_numbers(doc_id: str):
    return _doc_or_404(doc_id).numbers


class Ask(BaseModel):
    question: str = Field(min_length=2, max_length=500)


@app.post("/api/docs/{doc_id}/ask")
def ask(doc_id: str, body: Ask, request: Request):
    doc = _doc_or_404(doc_id)
    if _rate_limited(request):
        raise HTTPException(429, "Too many questions from this address. Try again in an hour.")
    return answer_question(doc, body.question.strip())


_SAFE_NAME = re.compile(r"[^\w .,()&'+-]+")


def _clean_name(filename: str | None) -> str:
    name = _SAFE_NAME.sub(" ", Path(filename or "document.pdf").stem)
    return " ".join(name.split())[:80] or "document"


@app.post("/api/docs")
def upload(request: Request, file: UploadFile = File(...)):
    # A plain (sync) handler: FastAPI runs it in a worker thread, so reading a PDF never blocks other visitors.
    if _rate_limited(request):
        raise HTTPException(429, "Too many uploads from this address. Try again in an hour.")
    if _uploads_full():
        raise HTTPException(429, "This free demo has had a lot of uploads this hour. Try a sample, or come back later.")
    data = file.file.read(config.MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"PDFs up to {config.MAX_UPLOAD_MB} MB, please.")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "That file isn't a PDF.")
    # One PDF is read at a time, so a burst of uploads can't use up the server's memory.
    if not _ingest_lock.acquire(timeout=config.UPLOAD_QUEUE_WAIT_S):
        raise HTTPException(503, "Busy reading another PDF. Try again in a minute.")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "upload.pdf"
            path.write_bytes(data)
            try:
                with pymupdf.open(path) as pdf:
                    if pdf.needs_pass:
                        raise HTTPException(400, "This PDF is password-protected.")
                    if pdf.page_count == 0:
                        raise HTTPException(400, "This PDF has no pages.")
                    if not config.OCR_UPLOADS and all(needs_ocr(p) for p in pdf.pages(0, min(pdf.page_count, config.MAX_PAGES))):
                        raise HTTPException(400, "This looks like a scanned PDF. Reading your own scans (OCR) needs more "
                                                 "memory than this free demo has. Try the scanned sample, or run the app "
                                                 "locally.")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(400, "This PDF couldn't be read.")
            try:
                doc = store.ingest(path, "u-" + uuid.uuid4().hex[:12], _clean_name(file.filename), ocr=config.OCR_UPLOADS)
            except Exception:
                raise HTTPException(400, "This PDF couldn't be read.")
    finally:
        _ingest_lock.release()
    return doc.meta


@app.get("/api/eval")
def eval_report():
    report = config.EVAL_DIR / "results" / "latest.json"
    if not report.exists():
        return JSONResponse({"runs": []})
    return json.loads(report.read_text(encoding="utf-8"))


# ---- the web app (frontend/dist), with SPA fallback
if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = (config.FRONTEND_DIST / path).resolve()
        if path and f.is_file() and config.FRONTEND_DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(config.FRONTEND_DIST / "index.html")
