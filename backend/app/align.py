"""Map a quote back to the exact words on the page.

The model is asked for a verbatim quote per claim. We never trust it: the quote is aligned
against the PDF's own words (fuzzy, so OCR noise and curly quotes don't break it), and the
citation shows the PDF's text, not the model's. A quote that can't be found is reported as
unverified instead of being highlighted somewhere plausible.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from .text import match_tokens, normalize

VERIFIED = 0.85    # at or above: the quote is really in the document
PARTIAL = 0.60     # between: probably there, with OCR noise or small edits


def _word_tokens(words: list[dict], start: int, end: int) -> tuple[list[str], list[int]]:
    """Normalised tokens for a word range, plus the word index each token came from."""
    toks, owner = [], []
    for i in range(start, end):
        for t in match_tokens(words[i]["t"]):
            toks.append(t)
            owner.append(i)
    return toks, owner


def best_span(words: list[dict], start: int, end: int, quote: str) -> tuple[float, int, int]:
    """Best-matching word range for `quote` inside words[start:end] -> (similarity, s, e)."""
    quote = normalize(quote)
    if "..." in quote or "…" in quote:  # the model stitched pieces together: match the longest piece
        quote = max(quote.replace("…", "...").split("..."), key=len)
    q = match_tokens(quote)
    toks, owner = _word_tokens(words, start, end)
    if not q or not toks:
        return 0.0, start, start
    best = (0.0, 0, 0)
    n, m = len(toks), len(q)
    sm = SequenceMatcher(autojunk=False)
    sm.set_seq2(q)
    first = set(q[:3])
    for length in range(max(1, m - 3), m + 4):
        for i in range(0, max(1, n - length + 1)):
            window = toks[i:i + length]
            if not window:
                continue
            # cheap pre-filter: windows that share none of the quote's opening words can't be best
            if m > 4 and not (first & set(window[:6])) and best[0] > 0.5:
                continue
            sm.set_seq1(window)
            r = sm.ratio()
            if r > best[0]:
                best = (r, i, i + len(window))
    sim, ti, tj = best
    if tj <= ti:
        return 0.0, start, start
    return round(sim, 3), owner[ti], owner[tj - 1] + 1


def status_for(similarity: float) -> str:
    if similarity >= VERIFIED:
        return "verified"
    if similarity >= PARTIAL:
        return "partial"
    return "unverified"
