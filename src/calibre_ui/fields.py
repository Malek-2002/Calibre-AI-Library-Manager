"""Pure helpers that turn metadata values into the strings Calibre's fields expect."""
import re
from datetime import date

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def join_authors(authors: list[str]) -> str:
    return " & ".join(a.strip() for a in authors if a and a.strip())


def join_tags(tags: list[str]) -> str:
    return ", ".join(t.strip() for t in tags if t and t.strip())


def identifiers(isbn: str | None) -> str | None:
    digits = re.sub(r"[^0-9Xx]", "", isbn or "")
    return f"isbn:{digits.upper()}" if len(digits) in (10, 13) else None


def one_line(text: str | None) -> str | None:
    return re.sub(r"\s+", " ", text).strip() if text and text.strip() else None


def split_series(series: str | None, index: float | None = None) -> tuple[str | None, float | None]:
    """'The Expanse #1' -> ('The Expanse', 1.0). A separate index argument wins if given."""
    if not series or not series.strip():
        return None, index
    m = re.match(r"^(.*?)\s*[#,]\s*(\d+(?:\.\d+)?)\s*$", series.strip())
    if m and m.group(1):
        return m.group(1).strip(), index if index is not None else float(m.group(2))
    return series.strip(), index


def parse_publish_date(value: str | None) -> date | None:
    """Accepts 'Apr 2013', 'April 2013', '2013', '2013-04', '2013-04-14', 'Apr 14, 2013', '14 Apr 2013'."""
    if not value:
        return None
    s = str(value).strip()
    try:
        if m := re.match(r"^(\d{4})(?:[-/.](\d{1,2})(?:[-/.](\d{1,2}))?)?(?:[T\s].*)?$", s):
            return date(int(m[1]), int(m[2] or 1), int(m[3] or 1))
        if m := re.match(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$", s):
            return date(int(m[3]), _MONTHS[m[1][:3].lower()], int(m[2]))
        if m := re.match(r"^(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})$", s):
            return date(int(m[3]), _MONTHS[m[2][:3].lower()], int(m[1]))
        if m := re.match(r"^([A-Za-z]{3,9})\.?,?\s+(\d{4})$", s):
            return date(int(m[2]), _MONTHS[m[1][:3].lower()], 1)
    except (KeyError, ValueError):
        return None
    return None


def format_pubdate(value: str | None, fmt: str) -> str | None:
    d = parse_publish_date(value)
    return d.strftime(fmt) if d else None


def rating_to_index(rating: float | None, item_count: int) -> int | None:
    """Index of the star item in Calibre's rating combo box: 0 = not rated, then 1..5 stars
    (or 0..10 half-stars when the box has 11 items). None = nothing to set."""
    if not rating or rating <= 0:
        return None
    r = max(0.0, min(5.0, float(rating)))
    idx = int(r * 2 + 0.5) if item_count >= 11 else int(r + 0.5)
    return idx or None
