"""HTTP API + the built web app, served from one process."""

from __future__ import annotations

import json
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


app = FastAPI(title="Cited PDF Chat", lifespan=lifespan)

_hits: dict[str, deque] = defaultdict(deque)
_hits_lock = threading.Lock()


def _rate_limited(request: Request) -> bool:
    if config.RATE_LIMIT_PER_HOUR <= 0:
        return False
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?")
    now = time.time()
    with _hits_lock:
        q = _hits[ip]
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= config.RATE_LIMIT_PER_HOUR:
            return True
        q.append(now)
    return False


def _doc_or_404(doc_id: str) -> store.Doc:
    doc = store.get(doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    return doc


@app.get("/api/health")
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
    return FileResponse(doc.pdf, media_type="application/pdf", headers={"Cache-Control": "private, max-age=3600"})


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


@app.post("/api/docs")
async def upload(request: Request, file: UploadFile = File(...)):
    if _rate_limited(request):
        raise HTTPException(429, "Too many uploads from this address. Try again in an hour.")
    data = await file.read(config.MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"PDFs up to {config.MAX_UPLOAD_MB} MB, please.")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "That file isn't a PDF.")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.pdf"
        path.write_bytes(data)
        try:
            with pymupdf.open(path) as pdf:
                if pdf.needs_pass:
                    raise HTTPException(400, "This PDF is password-protected.")
                if pdf.page_count == 0:
                    raise HTTPException(400, "This PDF has no pages.")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "This PDF couldn't be read.")
        name = Path(file.filename or "document.pdf").stem[:80] or "document"
        doc = store.ingest(path, "u-" + uuid.uuid4().hex[:12], name)
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

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = (config.FRONTEND_DIST / path).resolve()
        if path and f.is_file() and config.FRONTEND_DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(config.FRONTEND_DIST / "index.html")
