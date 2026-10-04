"""Deterministic ISBN helpers - no LLM needed when the ISBN is printed in the book."""
import re

_LABELED = re.compile(r"ISBN(?:-?1[03])?\s*[:#]?\s*([0-9][0-9\- ]{8,16}[0-9Xx])", re.I)
_BARE13 = re.compile(r"\b97[89](?:[- ]?\d){10}\b")


def _ok10(s: str) -> bool:
    if not re.fullmatch(r"\d{9}[\dX]", s):
        return False
    return sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(s)) % 11 == 0


def _ok13(s: str) -> bool:
    if not re.fullmatch(r"97[89]\d{10}", s):
        return False
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(s[:12]))
    return (10 - total % 10) % 10 == int(s[12])


def normalize_isbn(raw: str) -> str:
    """Return a checksum-valid ISBN (digits/X only) or ''."""
    s = re.sub(r"[^0-9Xx]", "", raw or "").upper()
    if len(s) >= 13 and _ok13(s[:13]):
        return s[:13]
    if len(s) >= 10 and _ok10(s[:10]):
        return s[:10]
    return ""


def find_isbn(text: str) -> str:
    """Best valid ISBN printed in `text` (ISBN-13 preferred), or ''."""
    candidates = [m.group(1) for m in _LABELED.finditer(text)]
    candidates += [m.group(0) for m in _BARE13.finditer(text)]
    valid = [n for n in (normalize_isbn(c) for c in candidates) if n]
    valid.sort(key=lambda n: len(n) != 13)  # stable: 13-digit first
    return valid[0] if valid else ""
