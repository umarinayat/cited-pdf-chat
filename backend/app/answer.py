"""Question -> answer whose every sentence is tied to highlighted, verified text in the PDF."""

from __future__ import annotations

import threading
import time

from . import align, config, llm
from .ingest import rects_for, sentence_spans, span_text
from .retrieval import embedder
from .text import numbers_in, tokens

SYSTEM = """You answer questions about one PDF document using ONLY the numbered sources provided (excerpts of that PDF).

Rules:
1. Use only facts stated in the sources. No outside knowledge and no assumptions.
2. Answer in 1-4 short sentences, in the same language as the question. Copy numbers exactly as the source writes them.
3. Give every sentence at least one citation: the source id (like "S2") and a quote of 4-30 words copied character-for-character from that source that supports the sentence. Never paraphrase inside a quote, never join text from different places into one quote, never use "...".
4. If the sources do not contain the answer, set answer_found to false and return an empty sentences list. Do not guess. If they answer only part of the question, answer that part and say what the document does not cover.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "answer_found": {"type": "boolean"},
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "citations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"source": {"type": "string"}, "quote": {"type": "string"}},
                            "required": ["source", "quote"],
                        },
                    },
                },
                "required": ["text", "citations"],
            },
        },
    },
    "required": ["answer_found", "sentences"],
}

HIGH, MEDIUM = 80, 60

_budget = {"day": "", "used": 0}
_budget_lock = threading.Lock()


def _take_budget() -> bool:
    """Count one model call against today's cap (DAILY_LLM_LIMIT, UTC days). False once it is used up."""
    if config.DAILY_LLM_LIMIT <= 0:
        return True
    today = time.strftime("%Y-%m-%d", time.gmtime())
    with _budget_lock:
        if _budget["day"] != today:
            _budget.update(day=today, used=0)
        if _budget["used"] >= config.DAILY_LLM_LIMIT:
            return False
        _budget["used"] += 1
        return True


def answer_question(doc, question: str) -> dict:
    t0 = time.perf_counter()
    hits = doc.index.search(question)
    sources = [{"chunk": h["chunk"], "page": doc.chunks[h["chunk"]]["page"], "score": h["score"]} for h in hits]
    result = None
    if llm.active() and _take_budget():
        try:
            result = _llm_answer(doc, question, hits)
        except llm.LLMError as e:
            result = _extractive(doc, question, hits)
            result["note"] = f"The language model call failed, so these are the closest passages instead. ({e})"
    else:
        result = _extractive(doc, question, hits)
        if llm.active():
            result["note"] = ("This public demo has used today's AI budget, so these are the closest passages "
                              "instead. It resets at midnight UTC.")
    result["sources"] = sources
    result["ms"] = int((time.perf_counter() - t0) * 1000)
    return result


# ---------------------------------------------------------------- model answers

def _llm_answer(doc, question: str, hits: list[dict]) -> dict:
    labels, blocks = {}, []
    for n, h in enumerate(hits, 1):
        c = doc.chunks[h["chunk"]]
        labels[f"S{n}"] = h["chunk"]
        blocks.append(f"[S{n}] (page {c['page'] + 1})\n{c['text']}")
    user = "SOURCES:\n\n" + "\n\n".join(blocks) + f"\n\nQUESTION: {question}"
    raw = llm.generate_json(SYSTEM, user, SCHEMA)
    provider, model = llm.active()[0], raw.get("_model")

    citations: list[dict] = []
    by_span: dict[tuple, int] = {}
    sentences = []
    for s in raw.get("sentences") or []:
        text = str(s.get("text", "")).strip()
        if not text:
            continue
        cites, cited_text = [], []
        for c in s.get("citations") or []:
            quote = str(c.get("quote", "")).strip()
            if not quote:
                continue
            found = _resolve(doc, str(c.get("source", "")).strip().strip("[]"), quote, labels)
            if found is None:
                continue
            sim, page, ws, we, chunk = found
            words = doc.pages[page]["words"]
            pdf_text = span_text(words, ws, we).replace("\n", " ")
            cited_text.append(doc.chunks[chunk]["text"])
            key = (page, ws, we)
            if key not in by_span:
                status = align.status_for(sim)
                support = _support(text, pdf_text, doc.chunks[chunk]["text"])
                by_span[key] = len(citations) + 1
                citations.append({
                    "n": by_span[key], "page": page, "rects": rects_for(words, ws, we) if status != "unverified" else [],
                    "text": pdf_text, "quote": quote, "similarity": sim, "support": round(support, 3),
                    "status": status, "score": _score(sim, support, status), "chunk": chunk,
                })
            cites.append(by_span[key])
        # Numbers guard: every number in the sentence must appear in what it cites
        # (numbers the question itself mentions, like a year, are exempt).
        sourced = set().union(*(numbers_in(t) for t in cited_text)) if cited_text else set()
        missing = numbers_in(text) - sourced - numbers_in(question)
        if missing:
            for n in cites:
                cit = citations[n - 1]
                cit["score"] = min(cit["score"], 55)
                cit.setdefault("warnings", []).append("numbers not in source: " + ", ".join(sorted(missing)))
        sentences.append({"text": text, "cites": sorted(set(cites)), "status": _sentence_status(cites, citations),
                          **({"unsourced_numbers": sorted(missing)} if missing else {})})

    for c in citations:
        c["label"] = "high" if c["score"] >= HIGH else "medium" if c["score"] >= MEDIUM else "low"
    found = bool(raw.get("answer_found")) and bool(sentences)
    out = {"mode": "llm", "provider": provider, "model": model, "found": found,
           "sentences": sentences if found else [], "citations": citations if found else []}
    if not found:
        out["closest"] = _closest(doc, question, hits)
    return out


def _resolve(doc, label: str, quote: str, labels: dict) -> tuple | None:
    """Find the quote in the cited source; if it isn't there, check the other sources
    (models sometimes cite the wrong id). Returns (similarity, page, start, end, chunk)."""
    order = ([labels[label]] if label in labels else []) + [c for c in labels.values() if labels.get(label) != c]
    best = None
    for rank, ci in enumerate(order):
        page, s, e = _window(doc, ci)
        sim, ws, we = align.best_span(doc.pages[page]["words"], s, e, quote)
        if rank == 0 and sim >= align.VERIFIED:
            return sim, page, ws, we, ci
        if best is None or sim > best[0] + 0.02:  # ties go to the source the model named
            best = (sim, page, ws, we, ci)
    return best


def _window(doc, ci: int) -> tuple[int, int, int]:
    """A chunk plus its neighbours on the same page, so quotes that cross a chunk edge still match."""
    c = doc.chunks[ci]
    start, end = c["start"], c["end"]
    if ci > 0 and doc.chunks[ci - 1]["page"] == c["page"]:
        start = doc.chunks[ci - 1]["start"]
    if ci + 1 < len(doc.chunks) and doc.chunks[ci + 1]["page"] == c["page"]:
        end = doc.chunks[ci + 1]["end"]
    return c["page"], start, end


def _support(sentence: str, quoted: str, chunk_text: str) -> float:
    """How much of the sentence the cited text actually backs up (0-1).

    Lexical: share of the sentence's content words found in the quote (or, discounted, in the
    surrounding chunk). Semantic: embedding similarity when the local model is available, so a
    faithful paraphrase is not punished.
    """
    want = set(tokens(sentence))
    if not want:
        return 1.0
    lexical = max(len(want & set(tokens(quoted))) / len(want), 0.85 * len(want & set(tokens(chunk_text))) / len(want))
    semantic = 0.0
    vecs = embedder.texts([sentence, quoted]) if embedder.ok else None
    if vecs is not None:
        cos = float(vecs[0] @ vecs[1])
        semantic = min(1.0, max(0.0, (cos - 0.55) / 0.35))  # bge-small: ~0.55 unrelated, ~0.9 paraphrase
    return max(lexical, semantic)


def _score(sim: float, support: float, status: str) -> int:
    score = 100 * (0.45 * sim + 0.55 * support)
    if status == "unverified":
        score = min(score, 35)
    return int(round(score))


def _sentence_status(cites: list[int], citations: list[dict]) -> str:
    good = [citations[n - 1] for n in cites if citations[n - 1]["status"] != "unverified"]
    if not good:
        return "unsupported"
    if max(c["score"] for c in good) >= MEDIUM:
        return "supported"
    return "weak"


# ---------------------------------------------------------------- no-key mode

def _passages(doc, question: str, hits: list[dict], limit: int) -> list[tuple]:
    """Sentences from the top chunks, scored by how much of the question's (IDF-weighted)
    vocabulary they contain. Question words the document never uses can't be matched by any
    sentence, so they don't count against it."""
    idf = doc.index.bm25.idf
    q = {t for t in tokens(question) if t in idf}
    total = sum(idf[t] for t in q)
    out = []
    for rank, h in enumerate(hits[:4]):
        c = doc.chunks[h["chunk"]]
        words = doc.pages[c["page"]]["words"]
        for s, e in sentence_spans(words, c["start"], c["end"]):
            text = span_text(words, s, e).replace("\n", " ")
            st = set(tokens(text))
            if not st or not total:
                continue
            overlap = sum(idf[t] for t in q & st) / total
            out.append((overlap, -rank, c["page"], s, e, text, h["chunk"]))
    out.sort(key=lambda x: (x[0], x[1]), reverse=True)
    picked, seen = [], set()
    for item in out:
        key = (item[2], item[3])
        if key in seen:
            continue
        seen.add(key)
        picked.append(item)
        if len(picked) == limit:
            break
    return picked


def _extractive(doc, question: str, hits: list[dict]) -> dict:
    picked = [p for p in _passages(doc, question, hits, 3) if p[0] >= 0.25]
    citations, sentences = [], []
    for overlap, _r, page, s, e, text, chunk in picked:
        n = len(citations) + 1
        score = int(round(100 * overlap))
        words = doc.pages[page]["words"]
        citations.append({"n": n, "page": page, "rects": rects_for(words, s, e), "text": text, "quote": text,
                          "similarity": 1.0, "support": round(overlap, 3), "status": "verified", "score": score,
                          "label": "high" if score >= HIGH else "medium" if score >= MEDIUM else "low", "chunk": chunk})
        sentences.append({"text": text, "cites": [n], "status": "passage"})
    found = bool(picked) and picked[0][0] >= 0.5
    out = {"mode": "extractive", "provider": None, "model": None, "found": found,
           "sentences": sentences if found else [], "citations": citations if found else []}
    if not found:
        out["closest"] = _closest(doc, question, hits)
    return out


def _closest(doc, question: str, hits: list[dict]) -> list[dict]:
    """Best passages to show under a "not in this document" answer, so the user can check for themselves."""
    res = []
    for overlap, _r, page, s, e, text, _c in _passages(doc, question, hits, 2):
        if overlap <= 0:
            continue
        res.append({"page": page, "text": text, "rects": rects_for(doc.pages[page]["words"], s, e)})
    return res
