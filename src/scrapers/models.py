from dataclasses import asdict, dataclass, field

_FIELDS = ("title", "authors", "rating", "tags", "series", "publisher", "publish_date", "comments", "isbn")


@dataclass
class ScrapedBook:
    source: str                    # "goodreads" | "amazon"
    url: str
    title: str = ""
    authors: list[str] = field(default_factory=list)
    rating: float = 0.0
    rating_count: int = 0
    tags: list[str] = field(default_factory=list)
    series: str = ""
    publisher: str = ""
    publish_date: str = ""         # "Mon YYYY" or "YYYY"
    comments: str = ""
    isbn: str = ""

    def fill(self, name: str, value) -> None:
        """Set a field only if it is still empty (first parser wins)."""
        if value and not getattr(self, name):
            setattr(self, name, value)

    def fields(self) -> dict:
        """Non-empty metadata fields, ready to merge into BookMetadata."""
        return {n: getattr(self, n) for n in _FIELDS if getattr(self, n)}

    def to_dict(self) -> dict:
        return asdict(self)
