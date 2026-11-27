"""Documents on disk (data/docs/<id>/) with an in-memory cache of their search indexes."""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
from pathlib import Path

import numpy as np

from . import config
from .ingest import build_chunks, extract_pages
from .numbers import extract_numbers
from .retrieval import Index, embedder

INGEST_VERSION = 11  # bump when extraction/chunking changes, so cached docs are rebuilt
DOCS = config.DATA_DIR / "docs"
ID_RE = re.compile(r"^[a-z0-9-]{1,48}$")

SAMPLES = [
    {"id": "sample-library", "file": "riverside-library-2025.pdf",
     "name": "Riverside Library Annual Report 2025", "kind": "Digital PDF"},
    {"id": "sample-library-scan", "file": "riverside-library-2025-scanned.pdf",
     "name": "Riverside Library Annual Report 2025", "kind": "Scanned copy (image-only, OCR)"},
]


class Doc:
    def __init__(self, meta: dict, pages: list, chunks: list, numbers: list, vectors):
        self.meta, self.pages, self.chunks, self.numbers = meta, pages, chunks, numbers
        self.index = Index(chunks, vectors)

    @property
    def pdf(self) -> Path:
        return DOCS / self.meta["id"] / "source.pdf"


_cache: dict[str, Doc] = {}
_lock = threading.Lock()


def ingest(pdf_path: Path, doc_id: str, name: str, kind: str = "Uploaded", sample: bool = False,
           ocr: bool = True) -> Doc:
    t0 = time.perf_counter()
    pages = extract_pages(str(pdf_path), max_pages=config.MAX_PAGES, ocr=ocr)
    chunks = build_chunks(pages)
    numbers = extract_numbers(pages)
    vectors = embedder.passages([c["text"] for c in chunks])
    folder = DOCS / doc_id
    folder.mkdir(parents=True, exist_ok=True)
    if Path(pdf_path).resolve() != (folder / "source.pdf").resolve():
        shutil.copyfile(pdf_path, folder / "source.pdf")
    meta = {
        "id": doc_id, "name": name, "kind": kind, "sample": sample,
        "pages": len(pages), "ocr_pages": sum(p["source"] == "ocr" for p in pages),
        "skipped_pages": sum(p["source"] == "none" for p in pages),
        "chunks": len(chunks), "numbers": len(numbers),
        "embeddings": vectors is not None, "embed_model": config.EMBED_MODEL if vectors is not None else None,
        "ingest_version": INGEST_VERSION, "ingest_ms": int((time.perf_counter() - t0) * 1000),
        "source_size": Path(pdf_path).stat().st_size,
    }
    (folder / "doc.json").write_text(
        json.dumps({"meta": meta, "pages": pages, "chunks": chunks, "numbers": numbers}, ensure_ascii=False),
        encoding="utf-8")
    if vectors is not None:
        np.save(folder / "vectors.npy", vectors)
    doc = Doc(meta, pages, chunks, numbers, vectors)
    _remember(doc_id, doc)
    return doc


def _remember(doc_id: str, doc: Doc) -> None:
    """Cache a document. Only the most recent uploads stay in memory, so many uploads can't use it all up."""
    with _lock:
        _cache.pop(doc_id, None)
        _cache[doc_id] = doc  # dicts keep insertion order: the newest is last
        uploads = [k for k in _cache if k.startswith("u-")]
        for k in uploads[: max(0, len(uploads) - config.MAX_CACHED_UPLOADS)]:
            _cache.pop(k, None)


def get(doc_id: str) -> Doc | None:
    if not ID_RE.match(doc_id or ""):
        return None
    with _lock:
        if doc_id in _cache:
            return _cache[doc_id]
    folder = DOCS / doc_id
    if not (folder / "doc.json").exists():
        return None
    data = json.loads((folder / "doc.json").read_text(encoding="utf-8"))
    vec_file = folder / "vectors.npy"
    vectors = np.load(vec_file) if vec_file.exists() else None
    if vectors is None and embedder.ok:  # embeddings became available since ingest
        vectors = embedder.passages([c["text"] for c in data["chunks"]])
        if vectors is not None:
            np.save(vec_file, vectors)
    doc = Doc(data["meta"], data["pages"], data["chunks"], data["numbers"], vectors)
    _remember(doc_id, doc)
    return doc


def ensure_samples() -> None:
    """Ingest the bundled sample PDFs, rebuilding them when the file or the pipeline changed."""
    for s in SAMPLES:
        src = config.SAMPLES_DIR / s["file"]
        if not src.exists():
            continue
        doc = get(s["id"])
        if doc and doc.meta.get("ingest_version") == INGEST_VERSION and doc.meta.get("source_size") == src.stat().st_size:
            continue
        with _lock:
            _cache.pop(s["id"], None)
        ingest(src, s["id"], s["name"], s["kind"], sample=True)


def prune_uploads(max_age_hours: float) -> int:
    """Delete uploaded documents older than max_age_hours (samples are never touched). Returns how many."""
    if max_age_hours <= 0 or not DOCS.exists():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for folder in DOCS.glob("u-*"):
        try:
            if folder.is_dir() and folder.stat().st_mtime < cutoff:
                with _lock:
                    _cache.pop(folder.name, None)
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def samples() -> list[dict]:
    out = []
    for s in SAMPLES:
        doc = get(s["id"])
        if doc:
            out.append(doc.meta)
    return out
