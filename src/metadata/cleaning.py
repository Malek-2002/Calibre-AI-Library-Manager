"""Small normalisers shared by every format and by LLM-answer validation."""
import re
from datetime import datetime, timezone
from typing import Any

from .models import BookMetadata

AUTHOR_SEP = r";|\n|&|\band\b"
TAG_SEP = r";|,|\n"

_PLACEHOLDERS = {"", "unknown", "n/a", "na", "none", "null", "not available", "unspecified", "-"}
_JUNK_TITLE = re.compile(
    r"(^untitled|^microsoft word\s*-|^title$|\.(docx?|indd|pdf|tex|qxd|pmd|rtf|txt|odt|epub)$)", re.I
)
_JUNK_AUTHORS = {"admin", "administrator", "user", "owner", "unknown", "author", "default", "root",
                 "anonymous", "unspecified", "nobody", "none"}


def clean_str(v: Any) -> str:
    if v is None:
        return ""
    s = re.sub(r"\s+", " ", str(v)).strip()
    return "" if s.lower() in _PLACEHOLDERS else s


def clean_list(v: Any, sep: str = r";|\n") -> list[str]:
    if v is None:
        return []
    items = re.split(sep, v) if isinstance(v, str) else list(v)
    seen, out = set(), []
    for item in items:
        s = clean_str(item)
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


_MONTHS = ["january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december"]


def _fmt(month: int, year: str | int) -> str:
    return f"{_MONTHS[month - 1][:3].title()} {year}"


def _month_index(word: str) -> int | None:
    w = word.lower()
    if len(w) < 3:
        return None
    for i, full in enumerate(_MONTHS):
        if full.startswith(w) or (w == "sept" and i == 8):
            return i + 1
    return None


def normalize_date(v: Any) -> str:
    """Canonical form: 'Jun 2011' (month known) or '2011' (year only).

    Accepts epoch milliseconds (Goodreads), ISO dates, 'June 1, 2011',
    '1 June 2011', 'Jun 2011', 'First published June 1, 2011', or free text with a year.
    """
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 1e10:
        try:
            d = datetime.fromtimestamp(v / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return ""
        return _fmt(d.month, d.year)
    s = clean_str(v)
    if not s:
        return ""
    if s.isdigit() and len(s) == 13:
        return normalize_date(int(s))
    m = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-\d{1,2})?(?:[T ].*)?", s)
    if m and 1 <= int(m[2]) <= 12:
        return _fmt(int(m[2]), m[1])
    for pat in (r"([A-Za-z]{3,9})\.?\s+(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?(\d{4})",
                r"\d{1,2}(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})"):
        for m in re.finditer(pat, s):
            idx = _month_index(m[1])
            if idx:
                return _fmt(idx, m[2])
    m = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", s)
    return m.group(1) if m else ""


def sanitize(meta: BookMetadata, file_stem: str = "") -> None:
    """Blank out embedded values that are tool leftovers, not real metadata."""
    title = meta.title.strip()
    if title and (_JUNK_TITLE.search(title) or title.lower() == file_stem.lower()):
        meta.title = ""
        meta.sources.pop("title", None)
    meta.authors = [a for a in meta.authors if a.strip("()[] ").lower() not in _JUNK_AUTHORS]
    if not meta.authors:
        meta.sources.pop("authors", None)
