"""Data classes used across the package."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from calibre_ui.errors import BookDataError
from calibre_ui.fields import one_line, split_series


@dataclass
class BookDetails:
    """What we know about the book and want to put into Calibre."""
    title: str
    authors: list[str]
    rating: float | None = None            # 0-5 (0/None = unknown)
    tags: list[str] = field(default_factory=list)
    series: str | None = None
    series_index: float | None = None
    publisher: str | None = None
    publish_date: str | None = None        # "Apr 2013", "2013", ISO...
    isbn: str | None = None
    comments: str | None = None

    @classmethod
    def from_any(cls, src: Any) -> "BookDetails":
        """Build from a dict or any object exposing the same attribute names."""
        get = src.get if isinstance(src, Mapping) else (lambda k, d=None: getattr(src, k, d))
        title = (get("title") or "").strip()
        authors = get("authors") or []
        authors = [authors] if isinstance(authors, str) else [a.strip() for a in authors if a and a.strip()]
        if not title or not authors:
            raise BookDataError("Both a title and at least one author are required to find the book in Calibre")
        series, index = split_series(get("series"), get("series_index"))
        tags = get("tags") or []
        return cls(
            title=title, authors=authors,
            rating=float(get("rating") or 0) or None,
            tags=[tags] if isinstance(tags, str) else list(tags),
            series=series, series_index=index,
            publisher=one_line(get("publisher")), publish_date=one_line(get("publish_date")),
            isbn=get("isbn") or None, comments=one_line(get("comments")),
        )


@dataclass
class TableRow:
    """One visible row of Calibre's book list."""
    values: dict[str, str]                 # column header -> cell text
    click_node: Any                        # the Title cell (what we click to select the row)
    selected: bool | None = None           # None = unknown / not requested


@dataclass
class FillReport:
    applied: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)   # field -> reason


class Outcome(str, Enum):
    ADDED = "added"                        # new book added + metadata written
    FORMAT_ADDED = "format_added"          # book existed; new format attached
    SKIPPED = "skipped_same_format"        # book and format already in Calibre


@dataclass
class AddResult:
    outcome: Outcome
    format: str
    fields_set: list[str] = field(default_factory=list)
    fields_failed: dict[str, str] = field(default_factory=dict)
    verified: bool | None = None           # re-searched after saving and found the book

    def to_dict(self) -> dict:
        return {"outcome": self.outcome.value, "format": self.format, "fields_set": self.fields_set,
                "fields_failed": self.fields_failed, "verified": self.verified}
