"""Tokenising and normalising text the same way everywhere (search, quote matching, scoring)."""

import re
import unicodedata

STOPWORDS = set(
    """a an and are as at be been but by can could did do does for from had has have how i if in into is it
    its me my of on or our per so than that the their them then there these they this to was we were what
    when where which who whom why will with would you your about after all also any before between both each
    few more most other over same some such only own very just under until up out off again further once here
    s t don should now""".split()
)

_WORD = re.compile(r"[a-z0-9]+(?:[.,:][0-9]+)*%?|[㐀-鿿豈-﫿]", re.IGNORECASE)
_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_NUM = re.compile(r"^\d[\d,]*(?:\.\d+)?%?$")


def normalize(text: str) -> str:
    """Fold quotes, dashes and width variants so a model's quote matches the PDF text."""
    text = unicodedata.normalize("NFKC", text)
    return (
        text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
        .replace("–", "-").replace("—", "-").replace("−", "-").replace(" ", " ")
    )


def norm_number(tok: str) -> str:
    """'182,450' -> '182450', '6.5%' -> '6.5'."""
    return tok.replace(",", "").rstrip("%")


def tokens(text: str, keep_stopwords: bool = False) -> list[str]:
    """Lower-cased word tokens. Numbers lose commas; CJK runs become characters plus bigrams."""
    raw = _WORD.findall(normalize(text).lower())
    out: list[str] = []
    prev_cjk = None
    for t in raw:
        if _CJK.fullmatch(t):
            out.append(t)
            if prev_cjk:
                out.append(prev_cjk + t)
            prev_cjk = t
            continue
        prev_cjk = None
        if _NUM.match(t):
            out.append(norm_number(t))
            continue
        if not keep_stopwords and t in STOPWORDS:
            continue
        if len(t) >= 4 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
            t = t[:-1]  # crude plural folding: visitors -> visitor, dvds -> dvd
        out.append(t)
    return out


def search_tokens(text: str) -> list[str]:
    """Tokens for the search index, plus each pair of neighbouring words glued together, so
    "maker space" (OCR) still finds "makerspace" and "e books" finds "ebooks"."""
    base = tokens(text)
    words = [t for t in base if t.isalpha() and len(t) >= 2]
    return base + [a + b for a, b in zip(words, words[1:])]


def match_tokens(text: str) -> list[str]:
    """Tokens for quote alignment: keep every word (stopwords included) so spans line up exactly."""
    return tokens(text, keep_stopwords=True)


def numbers_in(text: str) -> set[str]:
    """Normalised numbers that appear in a piece of text, ignoring 1-digit list markers."""
    found = set()
    for t in re.findall(r"\d[\d,]*(?:\.\d+)?", normalize(text)):
        n = norm_number(t)
        if len(n.replace(".", "")) >= 2:
            found.add(n)
    return found
