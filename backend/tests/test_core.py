import os
import tempfile
from pathlib import Path

import pymupdf
import pytest

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="cpc-test-")
os.environ["LLM_PROVIDER"] = "none"
os.environ["USE_EMBEDDINGS"] = "0"

from app import align, store  # noqa: E402
from app.ingest import build_chunks, extract_pages, rects_for, sentence_spans, span_text  # noqa: E402
from app.numbers import extract_numbers  # noqa: E402
from app.ocrfix import respace  # noqa: E402
from app.text import numbers_in, tokens  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "riverside-library-2025.pdf"


@pytest.mark.parametrize("raw, fixed", [
    ("TheSummerReadingChallengedrew1,240participantsaged4to17,whologged", "The Summer Reading Challenge drew 1,240 participants aged 4 to 17, who logged"),
    ("Weheld86 sessionswith an", "We held 86 sessions with an"),
    ("E-booksand audiobooksborrowed", "E-books and audiobooks borrowed"),
    ("3Dprinters, alasercutter", "3D printers, a laser cutter"),
    ("opened on14March2025 at820Alder Street.", "opened on 14 March 2025 at 820 Alder Street."),
    ("26,0o0 items", "26,000 items"),
    ("9:00-20:00 12:00-17:00", "9:00-20:00 12:00-17:00"),
    ("Library visits 171,300 182,450 +6.5%", "Library visits 171,300 182,450 +6.5%"),
    ("图书馆提供免费中文图书。", "图书馆提供免费中文图书。"),
    ("DVDs for 7 days", "DVDs for 7 days"),
])
def test_respace(raw, fixed):
    assert respace(raw) == fixed


def test_respace_keeps_repeated_names():
    assert respace("TheEastsideBranch", {"Eastside"}) == "The Eastside Branch"


def test_tokens_fold_numbers_and_plurals():
    assert tokens("Visits rose 6.5% to 182,450") == ["visit", "rose", "6.5", "182450"]
    assert "dvd" in tokens("DVDs for 7 days")
    assert numbers_in("cost $3.1 million in 2025, 7 days") == {"3.1", "2025"}


def _words(text):
    return [{"t": t, "b": [i * 10.0, 0, i * 10.0 + 8, 10], "blk": 0, "ln": 0} for i, t in enumerate(text.split())]


def test_align_finds_exact_and_noisy_quotes():
    words = _words("Members may borrow up to 25 items at a time. Books are loaned for 21 days, DVDs for 7 days.")
    sim, s, e = align.best_span(words, 0, len(words), "DVDs for 7 days")
    assert sim >= align.VERIFIED and " ".join(w["t"] for w in words[s:e]) == "DVDs for 7 days."
    sim, s, e = align.best_span(words, 0, len(words), "members may borrow up to 25 itens at a time")  # typo
    assert align.PARTIAL <= sim and words[s]["t"] == "Members"
    sim, _, _ = align.best_span(words, 0, len(words), "the director earns a large salary every year")
    assert align.status_for(sim) == "unverified"


def test_align_handles_ellipsis_quotes():
    words = _words("The Eastside Branch opened on 14 March 2025 at 820 Alder Street.")
    sim, s, e = align.best_span(words, 0, len(words), "The Eastside Branch opened ... at 820 Alder Street")
    assert sim >= align.VERIFIED


@pytest.fixture(scope="module")
def sample_pages():
    return extract_pages(str(SAMPLE))


def test_extract_and_chunk(sample_pages):
    assert len(sample_pages) == 6 and all(p["source"] == "text" for p in sample_pages)
    chunks = build_chunks(sample_pages)
    assert chunks and all(c["end"] > c["start"] for c in chunks)
    joined = " ".join(c["text"] for c in chunks)
    assert "182,450" in joined and "Page 3" not in joined  # running footers are left out of chunks


def test_sentences_do_not_break_wrapped_lines(sample_pages):
    words = sample_pages[2]["words"]
    sentences = [span_text(words, s, e).replace("\n", " ") for s, e in sentence_spans(words, 0, len(words))]
    assert any(s.startswith("Using the laser cutter requires a 45-minute safety induction") for s in sentences)


def test_numbers_have_row_and_column_labels(sample_pages):
    nums = extract_numbers(sample_pages)
    visits_2025 = [n for n in nums if n["value"] == "182,450" and n["page"] == 1]
    assert visits_2025 and visits_2025[0]["label"] == "Library visits (2025)"
    assert visits_2025[0]["rects"]
    money = {n["value"]: n for n in nums if n["page"] == 4}
    assert money["$3.1 million"]["number"] == 3_100_000
    assert not any(n["value"] == "2025" for n in nums)  # years are not statistics


def test_rects_cover_one_box_per_line(sample_pages):
    words = sample_pages[0]["words"]
    rects = rects_for(words, 0, len(words))
    assert len(rects) == len({(w["blk"], w["ln"], round(w["b"][1])) for w in words})


def test_api_end_to_end():
    from fastapi.testclient import TestClient

    from app.main import app

    store.ingest(SAMPLE, "sample-library", "Riverside", "Digital PDF", sample=True)
    client = TestClient(app)
    assert client.get("/api/health").json()["mode"] == "extractive"
    assert client.head("/api/health").status_code == 200
    if (Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html").exists():
        assert client.head("/").status_code == 200  # link previews and uptime checks use HEAD
    r = client.post("/api/docs/sample-library/ask", json={"question": "How long can I keep a DVD?"}).json()
    assert r["found"] and "7 days" in r["sentences"][0]["text"] and r["citations"][0]["rects"]
    assert client.get("/api/docs/sample-library/numbers").json()
    assert client.get("/api/docs/sample-library/file").content.startswith(b"%PDF")
    assert client.get("/api/docs/../etc/passwd").status_code == 404
    assert client.post("/api/docs", files={"file": ("x.pdf", b"not a pdf", "application/pdf")}).status_code == 400

    tiny = pymupdf.open()
    tiny.new_page().insert_text((72, 72), "Invoice total: $1,250.00 due on 1 May 2026.", fontsize=12)
    up = client.post("/api/docs", files={"file": ("invoice.pdf", tiny.tobytes(), "application/pdf")})
    assert up.status_code == 200, up.text
    meta = up.json()
    assert meta["pages"] == 1 and meta["numbers"] >= 1
    nums = client.get(f"/api/docs/{meta['id']}/numbers").json()
    assert any(n["value"] == "$1,250.00" for n in nums)


def test_daily_llm_budget(monkeypatch):
    from app import answer, config, llm

    monkeypatch.setattr(config, "DAILY_LLM_LIMIT", 2)
    monkeypatch.setattr(answer, "_budget", {"day": "", "used": 0})
    assert [answer._take_budget() for _ in range(3)] == [True, True, False]
    # once the cap is used up, a configured model is skipped and the answer says why
    monkeypatch.setattr(llm, "active", lambda: ("gemini", "test-model"))
    monkeypatch.setattr(answer, "_llm_answer", lambda *a: pytest.fail("model called past the daily cap"))
    doc = store.ingest(SAMPLE, "sample-budget", "Riverside", "Digital PDF", sample=True)
    r = answer.answer_question(doc, "How long can I keep a DVD?")
    assert "today's AI budget" in r["note"] and r["sentences"]


def test_prune_uploads_keeps_samples():
    import time

    old, new, sample = (store.DOCS / n for n in ("u-old000000001", "u-new000000001", "sample-old"))
    for folder in (old, new, sample):
        folder.mkdir(parents=True, exist_ok=True)
    past = time.time() - 3 * 3600
    os.utime(old, (past, past))
    os.utime(sample, (past, past))
    assert store.prune_uploads(2) == 1
    assert not old.exists() and new.exists() and sample.exists()
    assert store.prune_uploads(0) == 0


def test_uploads_without_ocr(monkeypatch):
    from fastapi.testclient import TestClient

    from app import config, ingest
    from app.main import app

    monkeypatch.setattr(config, "OCR_UPLOADS", False)
    monkeypatch.setattr(ingest, "ocr_page", lambda page: pytest.fail("OCR ran with OCR_UPLOADS off"))
    client = TestClient(app)
    assert client.get("/api/health").json()["ocr_uploads"] is False

    scan = SAMPLE.with_name("riverside-library-2025-scanned.pdf").read_bytes()
    r = client.post("/api/docs", files={"file": ("scan.pdf", scan, "application/pdf")})
    assert r.status_code == 400 and "scanned PDF" in r.json()["detail"]

    mixed = pymupdf.open()
    mixed.new_page().insert_text((72, 72), "Opening hours are 9:00 to 17:00 on weekdays, closed on Sundays.", fontsize=12)
    with pymupdf.open(stream=scan, filetype="pdf") as src:
        mixed.insert_pdf(src, from_page=0, to_page=0)  # one image-only page
    r = client.post("/api/docs", files={"file": ("mixed.pdf", mixed.tobytes(), "application/pdf")})
    assert r.status_code == 200, r.text
    meta = r.json()
    assert meta["pages"] == 2 and meta["skipped_pages"] == 1 and meta["ocr_pages"] == 0 and meta["chunks"] >= 1
