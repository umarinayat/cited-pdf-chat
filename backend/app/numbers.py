"""Find every statistic in a document: value, what it measures, the sentence around it, and where it is.

Deterministic on purpose: regexes over positioned words, no model call, so the table is complete
and every row can be highlighted on the page.
"""

from __future__ import annotations

import re

from .ingest import line_spans, rects_for, sentence_spans, span_text

_CURRENCY = r"(?:US\$|HK\$|A\$|C\$|\$|€|£|¥|Rs\.?)"
_NUM_TOKEN = re.compile(
    rf"^[(\[]?(?P<sign>[+\-−])?(?P<cur>{_CURRENCY})?(?P<num>\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|\d+(?:\.\d+)?)(?P<suf>%|[kKmMbB]n?)?[)\].,;:]*$"
)
_SCALE_WORDS = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "m": 1e6, "bn": 1e9, "k": 1e3}
_TIME = re.compile(r"^\d{1,2}:\d{2}")


def _is_year(num: str, has_cur: bool, suffix: str) -> bool:
    return not has_cur and not suffix and "," not in num and "." not in num and 1900 <= int(num) <= 2100


def extract_numbers(pages: list[dict]) -> list[dict]:
    items = []
    for p in pages:
        words = p["words"]
        lines = line_spans(words)
        line_of = {}
        for li, (s, e) in enumerate(lines):
            for i in range(s, e):
                line_of[i] = li
        sentences = sentence_spans(words, 0, len(words)) if words else []
        sent_of = {}
        for si, (s, e) in enumerate(sentences):
            for i in range(s, e):
                sent_of[i] = si

        i = 0
        while i < len(words):
            tok = words[i]["t"]
            if _TIME.match(tok):
                i += 1
                continue
            m = _NUM_TOKEN.match(tok)
            start, end = i, i + 1
            cur = None
            if m is None:
                # A currency symbol written as its own word: "$ 2.4"
                if re.fullmatch(_CURRENCY, tok) and i + 1 < len(words) and _NUM_TOKEN.match(words[i + 1]["t"]):
                    cur, i = tok, i + 1
                    tok = words[i]["t"]
                    m = _NUM_TOKEN.match(tok)
                    end = i + 1
                else:
                    i += 1
                    continue
            num, suffix = m.group("num"), (m.group("suf") or "")
            cur = cur or m.group("cur")
            if len(num.replace(",", "").replace(".", "")) < 2 and not (cur or suffix):
                i += 1  # skip list markers and single digits in prose
                continue
            if _is_year(num.replace(",", ""), bool(cur), suffix) or (not cur and not suffix and _is_date_or_address(words, start)):
                i += 1
                continue
            value = float(num.replace(",", ""))
            scale_word = ""
            if suffix.lower().rstrip("n") in ("k", "m", "b"):
                value *= {"k": 1e3, "m": 1e6, "b": 1e9}[suffix.lower().rstrip("n")]
            if end < len(words):
                nxt = re.sub(r"[^a-z]", "", words[end]["t"].lower())
                if nxt in _SCALE_WORDS and nxt not in ("m", "k"):
                    value *= _SCALE_WORDS[nxt]
                    scale_word = " " + words[end]["t"].rstrip(".,;:")
                    end += 1
                elif nxt in ("percent", "per") and words[end]["t"].lower().startswith("percent"):
                    suffix = "%"
                    end += 1
            sign = "-" if (m.group("sign") or "") in ("-", "−") else ""
            unit = "%" if suffix == "%" else (cur or "")
            display = f"{sign}{cur or ''}{num}{'%' if suffix == '%' else ''}{scale_word}"
            items.append({
                "id": len(items),
                "page": p["page"],
                "value": display,
                "number": -value if sign else value,
                "unit": unit or "count",
                "label": _label(words, lines, line_of, sentences, sent_of, start, end),
                "context": span_text(words, *sentences[sent_of[start]]).replace("\n", " ") if start in sent_of else "",
                "rects": rects_for(words, start, end),
            })
            i = end
    return items


def _label(words, lines, line_of, sentences, sent_of, start, end) -> str:
    """What the number measures. Table rows: the row label (+ column header). Prose: words before it."""
    li = line_of[start]
    s, e = lines[li]
    row_words = [w["t"] for w in words[s:e]]
    numeric = [bool(_NUM_TOKEN.match(t)) or bool(re.fullmatch(_CURRENCY, t)) for t in row_words]
    gaps = [words[j + 1]["b"][0] - words[j]["b"][2] for j in range(s, e - 1)]
    is_table_row = sum(numeric) >= 1 and any(g > 18 for g in gaps) and not re.search(r"[.!?]$", row_words[-1])
    if is_table_row:
        head = []
        for t, isnum in zip(row_words, numeric):
            if isnum:
                break
            head.append(t)
        label = " ".join(head).strip(" :-")
        col = _column_header(words, lines, li, start)
        if col and col.lower() not in label.lower():
            label = f"{label} ({col})" if label else col
        if label:
            return label
    # Prose. A noun right after the number usually names it ("26,000 items", "$450,000 gift");
    # otherwise (and for percentages) the words before it do ("cut electricity costs by 18%").
    ss, se = sentences[sent_of[start]] if start in sent_of else (s, e)
    after = []
    if not re.search(r"[,.;:)]$", words[end - 1]["t"]):
        for w in words[end:min(se, end + 4)]:
            t = w["t"].strip(",;:().")
            if not t or t.lower() in _STOP or _NUM_TOKEN.match(t):
                break
            after.append(t)
            if re.search(r"[,.;:)]$", w["t"]):
                break
    if after and not words[start]["t"].rstrip(",.;:").endswith("%"):
        return " ".join(after)
    raw = [w["t"] for w in words[max(ss, start - 6):start]]
    cut = max((k + 1 for k, t in enumerate(raw) if re.search(r"[,;:]$", t)), default=0)
    before = [t.strip(",;:()") for t in raw[cut:] if not _NUM_TOKEN.match(t)]  # stay within the clause
    while before and before[0].lower() in _STOP:
        before.pop(0)
    while before and before[-1].lower() in _STOP:
        before.pop()
    return " ".join(before)


_STOP = {"and", "or", "the", "a", "an", "to", "of", "by", "with", "for", "in", "on", "at", "from", "is", "was",
         "are", "were", "up", "rose", "fell"} - {"rose", "fell"}
_MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"}
_STREET = {"street", "st", "road", "rd", "avenue", "ave", "lane", "ln", "boulevard", "blvd", "drive", "dr", "way"}


def _is_date_or_address(words: list[dict], i: int) -> bool:
    """14 March 2025, March 14, 820 Alder Street: positions and dates, not statistics."""
    near = [re.sub(r"[^a-z]", "", w["t"].lower()) for w in words[max(0, i - 1):i + 4]]
    prev = near[0] if i > 0 else ""
    nxt = near[1 if i > 0 else 0:]
    if prev in _MONTHS or (nxt[1:2] and nxt[1] in _MONTHS):
        return True
    return any(t in _STREET for t in nxt[2:5]) and bool(nxt[1:2]) and words[i + 1]["t"][:1].isupper()


def _column_header(words, lines, li, idx) -> str:
    """Nearest line above (same table) with a non-numeric word sitting over this number's column."""
    x0, x1 = words[idx]["b"][0], words[idx]["b"][2]
    for up in range(li - 1, max(-1, li - 15), -1):
        s, e = lines[up]
        if e - s > 14:
            break  # hit a prose paragraph: no header
        for w in words[s:e]:
            b = w["b"]
            if b[2] >= x0 - 2 and b[0] <= x1 + 2:
                t = w["t"]
                if _NUM_TOKEN.match(t) and not re.fullmatch(r"(19|20)\d\d", t):
                    break  # numeric cell: keep looking further up
                if t[:1].isalpha() or re.fullmatch(r"(19|20)\d\d", t):
                    # take the whole header cell: adjacent words on that line that overlap the column
                    cell = [ww["t"] for ww in words[s:e] if ww["b"][2] >= x0 - 25 and ww["b"][0] <= x1 + 25]
                    return " ".join(cell)
    return ""
