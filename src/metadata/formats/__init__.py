"""Format registry. To add a format: create <fmt>.py with a BookMetadataExtractor subclass and register it."""
from pathlib import Path
from typing import Any

from ..extractor import BookMetadataExtractor
from .epub import EpubMetadataExtractor
from .pdf import PdfMetadataExtractor

EXTRACTORS: dict[str, type[BookMetadataExtractor]] = {
    ".pdf": PdfMetadataExtractor,
    ".epub": EpubMetadataExtractor,
}
SUPPORTED_EXTENSIONS = frozenset(EXTRACTORS)


class UnsupportedFormat(ValueError):
    pass


def get_extractor(path: Path | str, **kwargs: Any) -> BookMetadataExtractor:
    path = Path(path)
    try:
        return EXTRACTORS[path.suffix.lower()](path, **kwargs)
    except KeyError:
        raise UnsupportedFormat(f"no metadata extractor for '{path.suffix}' files") from None
