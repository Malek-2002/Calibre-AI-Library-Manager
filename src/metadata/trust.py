"""Distrust embedded metadata.

Metadata stored inside a book file is often wrong: placeholder dates ("Jan 0101"), the name of the
ebook-packaging company as "publisher", file names as titles, "admin" as author, shadow-library
watermarks, invalid ISBNs... This module rejects such values BEFORE they are used, so they show up as
"missing" and the LLM / Goodreads / Amazon steps can fill them with real data.

No dependencies on the rest of the project: works on any object with the usual attributes
(title, authors, publisher, publish_date, isbn, comments, series, tags, rating, and optionally a
`sources` dict that says where each value came from).

    from .trust import distrust_embedded, resolve_conflicts

    # 1) right after the file's own metadata was read, BEFORE the LLM / scrapers run:
    rejected = distrust_embedded(meta, book_path, assume_all_embedded=True)

    # 2) after scraper/LLM values are known: let better sources overrule weak embedded values
    notes = resolve_conflicts(meta, {"publisher": ("Century", "goodreads"), "publish_date": ("Jan 2013", "goodreads")})
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

EMBEDDED_SOURCES = {"embedded", "file"}      # `sources` tags that mean "read from the book file itself"
MIN_YEAR = 1450                              # nothing in a metadata field was published before this
EXTERNAL_WINS = ("publisher", "publish_date")  # fields where Goodreads/Amazon beat the embedded value

_SHADOW = r"welib|z-?lib(?:rary)?\b|libgen|library genesis|anna'?s archive|pdfdrive|ebook3000|dokumen\.pub|vdoc\.pub"
_TOOLING = (r"microsoft (?:word|office|powerpoint|excel)|libreoffice|openoffice|indesign|quarkxpress|pdfmaker|"
            r"distiller|ghostscript|\bcairo\b|\blatex\b|xetex|pdftex|pandoc|\bsigil\b|\bcalibre\b")
_PACKAGER = r"digital liaison|ebook (?:conversion|production|services)|e-?book (?:converter|packag)|\bconversion\b"

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I)


_TITLE_JUNK = _rx(r"^\s*$|^untitled|^(?:document|doc|scan|img|image|book)\s*\d*$|^microsoft (?:word|powerpoint|excel)\b"
                  r"|\.(?:docx?|pptx?|xlsx?|indd|qxd|pub|rtf|odt|tex|pdf|epub|mobi|azw3?)\s*$|^[0-9a-f]{16,}$|^[\d\s._-]+$")
_AUTHOR_JUNK = _rx(r"^\s*$|^(?:unknown|anonymous|admin(?:istrator)?|user|owner|authors?|calibre|none|null|n/?a|root|pc|"
                   r"windows user|publisher)$|@|https?://|www\.|^\d+$")
_PUBLISHER_JUNK = _rx(r"^\s*$|^(?:unknown|none|null|n/?a)$|" + _TOOLING + "|" + _PACKAGER)
_COMMENT_JUNK = _rx(r"^\s*$|^(?:no description|description|n/?a|none|unknown|lorem ipsum)\b|^\s*https?://\S+\s*$")
_TAG_JUNK = _rx(r"^\s*$|^(?:unknown|none|null|untitled|ebook|e-book|epub|pdf|calibre|book)$")
_SHADOW_RX = _rx(_SHADOW)


@dataclass
class Rejection:
    field: str
    value: object
    reason: str

    def __str__(self) -> str:
        return f"{self.field}={self.value!r} rejected: {self.reason}"


# --------------------------------------------------------------------------- #
# dates
# --------------------------------------------------------------------------- #
def parse_date_parts(value) -> tuple[int, int | None, int | None] | None:
    """'Jan 0101', '0101-01-01T00:00:00', '2013', '2013-04', 'Apr 14, 2013', 'D:20130414...' -> (y, m, d)."""
    if value is None:
        return None
    s = str(value).strip()
    if s.startswith("D:"):
        s = s[2:]
    try:
        if m := re.match(r"^(\d{4})(\d{2})(\d{2})(?:\d{2,6})?(?:Z|[+-]\d{2}'?\d{0,2}'?)?$", s):
            return int(m[1]), int(m[2]), int(m[3])
        if m := re.match(r"^(\d{4})(?:[-/.](\d{1,2})(?:[-/.](\d{1,2}))?)?(?:[T\s].*)?$", s):
            return int(m[1]), int(m[2]) if m[2] else None, int(m[3]) if m[3] else None
        if m := re.match(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$", s):
            return int(m[3]), _MONTHS[m[1][:3].lower()], int(m[2])
        if m := re.match(r"^(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})$", s):
            return int(m[3]), _MONTHS[m[2][:3].lower()], int(m[1])
        if m := re.match(r"^([A-Za-z]{3,9})\.?,?\s+(\d{4})$", s):
            return int(m[2]), _MONTHS[m[1][:3].lower()], None
    except KeyError:
        return None
    return None


def date_reason(value, today: date) -> str | None:
    parts = parse_date_parts(value)
    if parts is None:
        return "unrecognized date format"
    y, m, d = parts
    if m is not None and not 1 <= m <= 12:
        return f"month {m} is not valid"
    if y < MIN_YEAR:
        hint = " (year 101 / 0101 is the placeholder Calibre and many tools use for 'no date')" if y in (0, 1, 101) else ""
        return f"year {y} is not plausible{hint}"
    if y > today.year + 1:
        return f"year {y} is in the future"
    if d is not None and (y, m, d) in {(1970, 1, 1), (1900, 1, 1), (1899, 12, 30)}:
        return "looks like a default/epoch placeholder date"
    return None


# --------------------------------------------------------------------------- #
# per-field checks: each returns a reason to reject, or None
# --------------------------------------------------------------------------- #
def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", " ", s).strip().casefold()


def _valid_isbn(raw: str) -> bool:
    d = re.sub(r"[^0-9Xx]", "", str(raw)).upper()
    if len(d) == 13 and d.isdigit():
        return sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(d)) % 10 == 0
    if len(d) == 10 and d[:9].isdigit():
        return sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(d)) % 11 == 0
    return False


class _Ctx:
    def __init__(self, path: Path | None, today: date):
        self.stem = _norm(path.stem) if path else ""
        # "Dust.epub" with the title "Dust" is fine; "Dust_-_Hugh_Howey.epub" as a title is just the file name
        self.stem_has_author_part = bool(path and re.search(r"\s[-\u2013\u2014]{1,2}\s|_-_|--", path.stem))
        self.today = today


def _title_reason(v: str, c: _Ctx) -> str | None:
    if _TITLE_JUNK.search(v):
        return "placeholder / file-name / hash-like title"
    if _SHADOW_RX.search(v):
        return "contains a download-site watermark"
    if c.stem and c.stem_has_author_part and _norm(v) == c.stem:
        return "identical to the file name"
    return None


def _author_reason(v: str, c: _Ctx) -> str | None:
    if _AUTHOR_JUNK.search(v):
        return "placeholder author"
    if _SHADOW_RX.search(v):
        return "contains a download-site watermark"
    return None


def _publisher_reason(v: str, c: _Ctx) -> str | None:
    if _PUBLISHER_JUNK.search(v):
        return "software / ebook-packaging company, not the book's publisher"
    if _SHADOW_RX.search(v):
        return "contains a download-site watermark"
    return None


def _comments_reason(v: str, c: _Ctx) -> str | None:
    if _COMMENT_JUNK.search(v) or len(v.strip()) < 15:
        return "placeholder or too short to be a description"
    if _SHADOW_RX.search(v):
        return "contains a download-site watermark"
    return None


def _series_reason(v: str, c: _Ctx) -> str | None:
    return "contains a download-site watermark" if _SHADOW_RX.search(v) else None


def _tag_reason(v: str, c: _Ctx) -> str | None:
    if _TAG_JUNK.search(v) or _SHADOW_RX.search(v):
        return "junk tag"
    return None


def _isbn_reason(v: str, c: _Ctx) -> str | None:
    return None if _valid_isbn(v) else "fails the ISBN checksum"


def _rating_reason(v, c: _Ctx) -> str | None:
    try:
        return None if 1 <= float(v) <= 5 else f"{v} is outside 1-5"
    except (TypeError, ValueError):
        return "not a number"


def _empty(v) -> bool:
    return v is None or v == "" or v == [] or v == 0


def _cleared(v):
    return [] if isinstance(v, list) else "" if isinstance(v, str) else None


def _scalar(name: str, reason: Callable):
    def check(value, ctx):
        why = reason(value, ctx)
        return (_cleared(value), [Rejection(name, value, why)]) if why else (value, [])
    return check


def _list(name: str, reason: Callable):
    def check(values, ctx):
        kept, rejected = [], []
        for item in values:
            why = reason(str(item), ctx)
            (rejected if why else kept).append(Rejection(name, item, why) if why else item)
        return kept, rejected
    return check


def _date(name: str):
    def check(value, ctx):
        why = date_reason(value, ctx.today)
        return (_cleared(value), [Rejection(name, value, why)]) if why else (value, [])
    return check


_CHECKS: dict[str, Callable] = {
    "title": _scalar("title", _title_reason),
    "authors": _list("authors", _author_reason),
    "publisher": _scalar("publisher", _publisher_reason),
    "publish_date": _date("publish_date"),
    "isbn": _scalar("isbn", _isbn_reason),
    "comments": _scalar("comments", _comments_reason),
    "series": _scalar("series", _series_reason),
    "tags": _list("tags", _tag_reason),
    "rating": _scalar("rating", _rating_reason),
}


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def distrust_embedded(meta, path: Path | str | None = None, *, assume_all_embedded: bool = False,
                      today: date | None = None) -> list[Rejection]:
    """Clear impossible/placeholder values from `meta` (in place) and return what was rejected.

    assume_all_embedded=True: call it right after reading the file's own metadata, when every value
    is embedded. Otherwise only fields whose `meta.sources[field]` is an embedded tag are checked, so
    values that came from the LLM or Goodreads are never touched.
    """
    sources = getattr(meta, "sources", None)
    ctx = _Ctx(Path(path) if path else None, today or date.today())
    rejected: list[Rejection] = []
    for name, check in _CHECKS.items():
        value = getattr(meta, name, None)
        if _empty(value):
            continue
        if not assume_all_embedded and sources and sources.get(name) not in EMBEDDED_SOURCES:
            continue
        new_value, found = check(value, ctx)
        if found:
            setattr(meta, name, new_value)
            rejected += found
            if _empty(new_value) and sources:
                sources.pop(name, None)       # now missing: later steps may fill it
    return rejected


def _publisher_key(s: str) -> str:
    s = _norm(s)
    s = re.sub(r"\b(?:inc|llc|ltd|limited|co|company|corp|corporation|group|publishing|publishers|publisher)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _disagree(field: str, a, b) -> bool:
    if field == "publisher":
        ka, kb = _publisher_key(str(a)), _publisher_key(str(b))
        return bool(ka and kb) and not (ka == kb or ka in kb or kb in ka)
    if field == "publish_date":
        pa, pb = parse_date_parts(a), parse_date_parts(b)
        return bool(pa and pb) and pa[0] != pb[0]
    return _norm(str(a)) != _norm(str(b))


def resolve_conflicts(meta, external: Mapping[str, tuple[object, str]]) -> list[str]:
    """Reconcile embedded values with values found by better sources.

    external: {field: (value, source_name)} for values the scrapers / LLM actually found.
      - field empty            -> filled from the external source
      - embedded, disagrees    -> publisher/publish_date: the external value wins; other fields: kept + noted
    Returns human-readable notes (put them in your result's errors/warnings list).
    """
    sources = getattr(meta, "sources", None)
    notes: list[str] = []
    for name, (value, src) in external.items():
        if _empty(value):
            continue
        current = getattr(meta, name, None)
        if _empty(current):
            setattr(meta, name, value)
            if sources is not None:
                sources[name] = src
            continue
        embedded = sources is None or sources.get(name) in EMBEDDED_SOURCES
        if not embedded or not _disagree(name, current, value):
            continue
        if name in EXTERNAL_WINS:
            setattr(meta, name, value)
            if sources is not None:
                sources[name] = src
            notes.append(f"{name}: embedded {current!r} replaced by {value!r} from {src}")
        else:
            notes.append(f"{name}: embedded {current!r} disagrees with {src} {value!r} (kept embedded)")
    return notes