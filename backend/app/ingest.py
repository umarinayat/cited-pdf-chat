"""PDF -> pages of positioned words -> retrieval chunks.

Every word keeps its bounding box (PDF points, top-left origin), so anything we cite
can be drawn back onto the page. Pages without a usable text layer are OCR'd.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
import threading

import numpy as np
import pymupdf as fitz

from .ocrfix import repeated_names, respace

OCR_MIN_CHARS = 25        # fewer text-layer characters than this -> treat the page as scanned
OCR_DPI = 200
CHUNK_TARGET_WORDS = 90   # close a chunk at the next paragraph break after this many words
CHUNK_MAX_WORDS = 150     # hard ceiling

_ocr_engine = None
_ocr_lock = threading.Lock()


def _ocr():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr_engine = RapidOCR()
    return _ocr_engine


def ocr_page(page: fitz.Page, dpi: int = OCR_DPI) -> list[tuple]:
    """OCR one page -> text lines (x0, y0, x1, y1, text) in reading order, in PDF points."""
    zoom = dpi / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    bgr = img[:, :, ::-1].copy()  # RapidOCR expects BGR like OpenCV
    found = []
    with _ocr_lock:
        # Two detection passes: the default box expansion sometimes fuses two tight lines into one
        # box (and reads only one of them); a tighter expansion sometimes drops a faint line.
        for unclip in (1.6, 1.3):
            result, _ = _ocr()(bgr, unclip_ratio=unclip)
            for item in result or []:
                xs = [p[0] for p in item[0]]
                ys = [p[1] for p in item[0]]
                found.append((min(xs) / zoom, min(ys) / zoom, max(xs) / zoom, max(ys) / zoom, item[1]))
    boxes = _merge_passes(found)
    # Reading order: rows by vertical centre (a tolerance of half a line), then left to right.
    boxes.sort(key=lambda b: (b[1] + b[3]) / 2)
    heights = sorted(b[3] - b[1] for b in boxes) or [10]
    tol = heights[len(heights) // 2] * 0.5
    rows: list[list] = []
    for b in boxes:
        cy = (b[1] + b[3]) / 2
        if rows and abs(cy - rows[-1][0]) <= tol:
            rows[-1][1].append(b)
            rows[-1][0] = sum((x[1] + x[3]) / 2 for x in rows[-1][1]) / len(rows[-1][1])
        else:
            rows.append([cy, [b]])
    return [b for _, row in rows for b in sorted(row, key=lambda b: b[0])]


def _merge_passes(found: list[tuple]) -> list[tuple]:
    """Union of both passes, thinnest boxes first; a box is dropped when it mostly overlaps one
    already kept, or overlaps it vertically and reads the same text (a fused two-line box)."""
    def iou(a, b):
        ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
        inter = ix * iy
        union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
        return inter / union if union > 0 else 0.0

    def squash(t):
        return re.sub(r"\W", "", t.lower())

    kept: list[tuple] = []
    for b in sorted(found, key=lambda b: b[3] - b[1]):
        dup = False
        for k in kept:
            if iou(b, k) > 0.5:
                dup = True
                break
            v_overlap = min(b[3], k[3]) - max(b[1], k[1])
            if v_overlap > 0 and min(b[2], k[2]) > max(b[0], k[0]):
                sb, sk = squash(b[4]), squash(k[4])
                if sb and sk and SequenceMatcher(None, sb, sk, autojunk=False).ratio() > 0.8:
                    dup = True
                    break
        if not dup:
            kept.append(b)
    return kept


def ocr_words(lines: list[tuple], names: set[str]) -> list[dict]:
    """Split OCR text lines into words, restoring dropped spaces, with boxes estimated per word."""
    words: list[dict] = []
    for line_no, (x0, y0, x1, y1, text) in enumerate(lines):
        parts = respace(text, names).split()
        if not parts:
            continue
        # Spread the line's width over its words in proportion to their length.
        total = sum(len(p) for p in parts) + len(parts) - 1
        unit = (x1 - x0) / max(total, 1)
        cx = x0
        for p in parts:
            w = unit * len(p)
            words.append({"t": p, "b": [round(cx, 2), round(y0, 2), round(cx + w, 2), round(y1, 2)],
                          "blk": line_no, "ln": 0})
            cx += w + unit
    return words


def extract_pages(pdf_path: str, max_pages: int | None = None) -> list[dict]:
    doc = fitz.open(pdf_path)
    pages, scanned = [], {}
    for pno, page in enumerate(doc):
        if max_pages is not None and pno >= max_pages:
            break
        words = [
            {"t": w[4], "b": [round(w[0], 2), round(w[1], 2), round(w[2], 2), round(w[3], 2)],
             "blk": int(w[5]), "ln": int(w[6])}
            for w in page.get_text("words")
        ]
        if sum(len(w["t"]) for w in words) < OCR_MIN_CHARS:
            lines = ocr_page(page)
            if lines:
                scanned[pno] = lines
        pages.append({
            "page": pno,
            "width": round(page.rect.width, 2),
            "height": round(page.rect.height, 2),
            "source": "ocr" if pno in scanned else "text",
            "words": words,
        })
    doc.close()
    # Names are learnt from the whole document before any OCR line is re-spaced.
    names = repeated_names([line[4] for lines in scanned.values() for line in lines])
    for p in pages:
        if p["page"] in scanned:
            p["words"] = ocr_words(scanned[p["page"]], names)
        assign_layout(p["words"])
    return pages


def assign_layout(words: list[dict]) -> None:
    """Rewrite each word's line ("ln") and paragraph ("blk") ids from geometry.

    Lines: consecutive words that overlap vertically, so a table row whose cells were drawn as
    separate text objects (or OCR'd as separate boxes) reads as one line.
    Paragraphs: a vertical gap larger than ~70% of the typical line height, or a jump back up the
    page. (PDF writers often put every wrapped line in its own block, so blocks can't be trusted.)
    """
    line_id, y0, y1, first = -1, None, None, []
    for i, w in enumerate(words):
        a, b = w["b"][1], w["b"][3]
        if y0 is None or (min(b, y1) - max(a, y0)) < 0.5 * min(max(b - a, 1), max(y1 - y0, 1)):
            line_id += 1
            y0, y1 = a, b
            first.append(i)
        else:
            y0, y1 = min(y0, a), max(y1, b)
        w["ln"] = line_id
    if not words:
        return
    starts = first + [len(words)]
    heights = sorted(max(w["b"][3] - w["b"][1], 1) for w in words)
    typical = heights[len(heights) // 2]
    para, prev_bottom = 0, None
    for li in range(len(first)):
        s, e = starts[li], starts[li + 1]
        top = min(w["b"][1] for w in words[s:e])
        if prev_bottom is not None:
            gap = top - prev_bottom
            # New paragraph: a blank gap, or reading order jumped back up (next column/box).
            if gap > 0.7 * typical or gap < -typical:
                para += 1
        for w in words[s:e]:
            w["blk"] = para
        prev_bottom = max(w["b"][3] for w in words[s:e])


def line_spans(words: list[dict]) -> list[tuple[int, int]]:
    """[start, end) word ranges, one per text line, in reading order."""
    spans, start, key = [], 0, None
    for i, w in enumerate(words):
        k = (w["blk"], w["ln"])
        if k != key:
            if key is not None:
                spans.append((start, i))
            start, key = i, k
    if words:
        spans.append((start, len(words)))
    return spans


def span_text(words: list[dict], start: int, end: int) -> str:
    """Join words, putting a newline wherever the line changes."""
    out, key = [], None
    for w in words[start:end]:
        k = (w["blk"], w["ln"])
        if key is not None and k != key:
            out.append("\n")
        elif out:
            out.append(" ")
        out.append(w["t"])
        key = k
    return "".join(out)


def furniture(pages: list[dict]) -> set[tuple[int, int]]:
    """(page, first word index) of running headers/footers: lines near the top or bottom edge whose
    text, with digits masked, repeats on several pages ("Page 3", "Annual Report 2025")."""
    seen: dict[str, set[int]] = {}
    candidates = []
    for p in pages:
        words, h = p["words"], p["height"] or 1
        for s, e in line_spans(words):
            cy = (min(w["b"][1] for w in words[s:e]) + max(w["b"][3] for w in words[s:e])) / 2
            if 0.09 * h < cy < 0.91 * h:
                continue
            key = re.sub(r"\d+", "#", " ".join(w["t"] for w in words[s:e]).lower())
            seen.setdefault(key, set()).add(p["page"])
            candidates.append((key, p["page"], s))
    need = max(2, int(0.4 * len(pages)))
    return {(pg, s) for key, pg, s in candidates
            if len(seen[key]) >= need or re.fullmatch(r"page #( of #)?", key)}


def build_chunks(pages: list[dict]) -> list[dict]:
    """Group lines into ~90-word chunks, preferring to break between paragraphs (blocks).
    Running headers and footers are left out of the chunks (they stay highlightable on the page)."""
    skip = furniture(pages)
    chunks = []
    for p in pages:
        words = p["words"]
        cstart, count = None, 0
        for s, e in line_spans(words):
            if (p["page"], s) in skip:
                if cstart is not None:
                    chunks.append(_chunk(p, cstart, s, len(chunks)))
                    cstart = None
                continue
            if cstart is None:
                cstart, count = s, 0
            count += e - s
            paragraph_ends = e >= len(words) or words[e]["blk"] != words[s]["blk"]
            if count >= CHUNK_MAX_WORDS or (count >= CHUNK_TARGET_WORDS and paragraph_ends):
                chunks.append(_chunk(p, cstart, e, len(chunks)))
                cstart = None
        if cstart is not None:
            chunks.append(_chunk(p, cstart, len(words), len(chunks)))
    return chunks


def _chunk(page: dict, start: int, end: int, idx: int) -> dict:
    return {"id": idx, "page": page["page"], "start": start, "end": end,
            "text": span_text(page["words"], start, end)}


_ABBREV = {"no.", "dr.", "mr.", "mrs.", "ms.", "st.", "e.g.", "i.e.", "vs.", "etc.", "inc.", "u.s.", "fig."}


def sentence_spans(words: list[dict], start: int, end: int) -> list[tuple[int, int]]:
    """Split a word range into sentences: at ., ?, ! (not abbreviations), at paragraph breaks,
    and at the end of lines that are not wrapped prose: short lines (headings) and lines with
    wide gaps between words (table rows)."""
    if not words:
        return []
    right = max(w["b"][2] for w in words)
    left = min(w["b"][0] for w in words)
    line_end = {}  # last word index of each line -> is that line "not wrapped prose"?
    for s, e in line_spans(words):
        gaps = [words[j + 1]["b"][0] - words[j]["b"][2] for j in range(s, e - 1)]
        short = words[e - 1]["b"][2] < left + 0.8 * (right - left)
        line_end[e - 1] = short or any(g > 18 for g in gaps)
    spans, s = [], start
    for i in range(start, end):
        t = words[i]["t"]
        boundary = i == end - 1
        if not boundary and re.search(r"[.?!。！？][\"')\]]*$", t) and t.lower() not in _ABBREV:
            boundary = True
        if not boundary and i in line_end:
            if words[i]["blk"] != words[i + 1]["blk"]:
                boundary = True
            elif line_end[i] and not re.search(r"[,;:\-]$", t):
                boundary = True
        if boundary:
            spans.append((s, i + 1))
            s = i + 1
    return [(a, b) for a, b in spans if b > a]


def rects_for(words: list[dict], start: int, end: int) -> list[list[float]]:
    """One highlight rectangle per text line covered by the word range."""
    rects: dict[tuple, list[float]] = {}
    order = []
    for w in words[start:end]:
        k = (w["blk"], w["ln"], round(w["b"][1]))
        b = w["b"]
        if k not in rects:
            rects[k] = list(b)
            order.append(k)
        else:
            r = rects[k]
            r[0], r[1], r[2], r[3] = min(r[0], b[0]), min(r[1], b[1]), max(r[2], b[2]), max(r[3], b[3])
    return [[round(v, 2) for v in rects[k]] for k in order]
