"""Hybrid search over a document's chunks: BM25 keywords + dense embeddings, fused with RRF.

Dense search uses a small local model (fastembed, ONNX), so it needs no API key. If the model
can't load, search quietly falls back to BM25 alone.
"""

from __future__ import annotations

import logging
import math
import threading
from collections import Counter

import numpy as np

from . import config
from .text import search_tokens

log = logging.getLogger(__name__)


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg = (sum(self.len) / len(docs)) if docs else 1.0
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(len(self.tf))
        for i, tf in enumerate(self.tf):
            norm = self.k1 * (1 - self.b + self.b * self.len[i] / self.avg)
            s = 0.0
            for t in query:
                f = tf.get(t)
                if f:
                    s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / (f + norm)
            out[i] = s
        return out


class Embedder:
    """Lazy, shared fastembed model. `ok` is False if it could not be loaded."""

    def __init__(self):
        self._model = None
        self._lock = threading.Lock()
        self.ok = config.USE_EMBEDDINGS
        self.error = ""

    def _load(self):
        if self._model is None and self.ok:
            try:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(model_name=config.EMBED_MODEL)
            except Exception as e:  # no network, missing wheels, ...
                self.ok, self.error = False, str(e)
                log.warning("dense retrieval disabled: %s", e)
        return self._model

    def passages(self, texts: list[str]) -> np.ndarray | None:
        with self._lock:
            m = self._load()
            if m is None or not texts:
                return None
            v = np.array(list(m.passage_embed(texts)), dtype=np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True).clip(1e-9)

    def query(self, text: str) -> np.ndarray | None:
        with self._lock:
            m = self._load()
            if m is None:
                return None
            v = np.array(list(m.query_embed([text]))[0], dtype=np.float32)
        return v / max(np.linalg.norm(v), 1e-9)

    def texts(self, texts: list[str]) -> np.ndarray | None:
        """Symmetric embeddings (no query prefix) for comparing two statements."""
        with self._lock:
            m = self._load()
            if m is None or not texts:
                return None
            v = np.array(list(m.embed(texts)), dtype=np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True).clip(1e-9)


embedder = Embedder()


class Index:
    def __init__(self, chunks: list[dict], vectors: np.ndarray | None):
        self.chunks = chunks
        self.bm25 = BM25([search_tokens(c["text"]) for c in chunks])
        self.vectors = vectors

    def search(self, question: str, k: int = config.TOP_K) -> list[dict]:
        """Top-k chunks as [{"chunk": idx, "score": rrf, "bm25": raw, "dense": cosine|None}]."""
        if not self.chunks:
            return []
        bm = self.bm25.scores(search_tokens(question))
        rankings = [np.argsort(-bm)]
        dense = None
        if self.vectors is not None and len(self.vectors) == len(self.chunks):
            q = embedder.query(question)
            if q is not None:
                dense = self.vectors @ q
                rankings.append(np.argsort(-dense))
        fused = np.zeros(len(self.chunks))
        for order in rankings:
            for rank, idx in enumerate(order):
                fused[idx] += 1.0 / (60 + rank)
        top = [int(i) for i in np.argsort(-fused)[:k]]
        return [
            {"chunk": i, "score": round(float(fused[i]), 5), "bm25": round(float(bm[i]), 3),
             "dense": None if dense is None else round(float(dense[i]), 3)}
            for i in top
        ]
