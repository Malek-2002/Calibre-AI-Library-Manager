from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Fields the LLM can supply (file_size is always measured locally).
FIELDS = (
    "title", "authors", "rating", "tags", "series",
    "publisher", "publish_date", "comments", "isbn",
)


@dataclass
class BookMetadata:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    file_size: int = 0            # bytes
    rating: float = 0.0           # 1-5, 0 = unknown
    tags: list[str] = field(default_factory=list)
    series: str = ""              # "Series Name #3"
    publisher: str = ""
    publish_date: str = ""        # "Mon YYYY" or "YYYY"
    comments: str = ""
    isbn: str = ""                # digits only (ISBN-13 preferred)
    sources: dict[str, str] = field(default_factory=dict)  # field -> where it came from

    def missing(self) -> list[str]:
        return [f for f in FIELDS if not getattr(self, f)]

    def fill(self, name: str, value: Any, source: str) -> bool:
        """Set `name` only if it is currently empty and `value` is non-empty."""
        if value and not getattr(self, name):
            setattr(self, name, value)
            self.sources[name] = source
            return True
        return False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExtractionResult:
    path: Path
    metadata: BookMetadata
    text_source: str = "none"             # "text" | "ocr" | "mixed" | "none"
    llm_used: bool = False
    llm_confidence: float | None = None
    llm_raw: dict | None = None           # untouched LLM answer, for the verification phase
    scraped: list[dict] = field(default_factory=list)   # raw per-site results (goodreads/amazon)
    identity: dict | None = None          # LLM identification used to build the search query
    errors: list[str] = field(default_factory=list)

    @property
    def missing(self) -> list[str]:
        return self.metadata.missing()

    @property
    def complete(self) -> bool:
        return not self.missing

    def to_dict(self) -> dict:
        d = asdict(self)
        d["path"] = str(self.path)
        d["missing"] = self.missing
        d["complete"] = self.complete
        return d
