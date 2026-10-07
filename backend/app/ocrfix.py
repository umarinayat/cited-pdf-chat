"""Put back the spaces OCR drops between English words.

The bundled PP-OCR recogniser (Chinese + English) often returns "TheSummerReadingChallengedrew1,240".
We re-split such runs with a word-frequency model (wordninja), but only accept a split when every
piece is a real word, and never split a capitalised word the document repeats (so names like
"Eastside" survive while "Weheld" becomes "We held"). Chinese text is left as is.
"""

from __future__ import annotations

import re

import wordninja

_VOCAB = wordninja.DEFAULT_LANGUAGE_MODEL._wordcost
_TOKEN = re.compile(r"[　-〿㐀-鿿豈-﫿＀-￯]+|[A-Za-z']+|\d[\d,.:]*%?|[^\sA-Za-z\d]")
_GLUE_BEFORE = set(",.;:!?%)]-/–")


def _ok(pieces: list[str]) -> bool:
    """Accept a split when it has no stray letters and is mostly dictionary words
    (plurals and possessives like "childrens" can be missing from the word list)."""
    if len(pieces) < 2 or any(len(p) == 1 and p.lower() not in ("a", "i") for p in pieces):
        return False
    known = sum(p.lower().strip("'") in _VOCAB for p in pieces)
    return known >= 0.7 * len(pieces) and all(p.lower().strip("'") in _VOCAB or len(p) >= 4 for p in pieces)


def _split_letters(run: str, keep: set[str]) -> list[str]:
    if run == "lt":
        return ["It"]  # the classic OCR l/I confusion
    parts = re.findall(r"[A-Z]{2,}s?(?![a-z])|[A-Z]?[a-z']+|[A-Z]+(?![a-z])", run) or [run]  # camelCase, DVDs
    out: list[str] = []
    for p in parts:
        low = p.lower().strip("'")
        if low in _VOCAB or len(low) <= 2 or p in keep or re.fullmatch(r"[A-Z]{2,}s?", p):  # names, DVDs
            out.append(p)
            continue
        pieces = wordninja.split(p)
        out.extend(pieces if _ok(pieces) else [p])
    return out


def repeated_names(texts: list[str]) -> set[str]:
    """Capitalised words the dictionary doesn't know but the document uses more than once
    ("Eastside", "Makerspace"): names, not merged words, so they must not be split."""
    counts: dict[str, int] = {}
    for t in texts:
        for w in re.findall(r"[A-Z][a-z]{3,}(?![a-z])", t):  # also inside fused runs: "theEastsideBranch"
            if w.lower() not in _VOCAB:
                counts[w] = counts.get(w, 0) + 1
    return {w for w, c in counts.items() if c >= 2}


def _unit_prefix(m: re.Match) -> str:
    """3Dprinters -> 3D printers, but leave 14March and 820Alder alone."""
    word = m.group(2) + m.group(3)
    if word.lower() in _VOCAB or m.group(3).lower() not in _VOCAB:
        return m.group(0)
    return f"{m.group(1)}{m.group(2)} {m.group(3)}"


def respace(text: str, keep: set[str] = frozenset()) -> str:
    text = re.sub(r"(?<=[\d,])[oO](?=[\d,])", "0", text)  # 26,0o0 -> 26,000
    text = re.sub(r"(\d)([A-Z])([a-z]{3,})", _unit_prefix, text)
    out: list[str] = []
    prev = None
    opening = False  # the last token was an opening quote
    for m in _TOKEN.finditer(text):
        tok = m.group(0)
        spaced = m.start() == 0 or text[m.start() - 1].isspace()
        if tok[0].isalpha() and tok[0] < "　" or tok[0] == "'":
            kind = "L"
        elif tok[0].isdigit():
            kind = "D"
        elif tok[0] >= "　":
            kind = "C"
        else:
            kind = "P"
        pieces = _split_letters(tok, keep) if kind == "L" else [tok]
        glue = False
        if out and opening:
            glue = True
        elif out and not spaced:
            glue = (
                (kind == "P" and tok in _GLUE_BEFORE)
                or (kind == "P" and tok == '"')  # closing quote
                or (prev == "P" and out[-1][-1] in "([$-/+–−")
                or (prev == "D" and kind == "L" and len(tok) < 2 and tok.isupper())  # 3D, not "96,800e-books"
                or kind == "C" or prev == "C"
            )
        opening = tok == '"' and (spaced or not out)
        for i, p in enumerate(pieces):
            if out and not (glue and i == 0):
                out.append(" ")
            out.append(p)
        prev = kind
    return "".join(out)
