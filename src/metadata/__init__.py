"""Book metadata extraction (format-independent API).

    from metadata import get_book_metadata
    data = get_book_metadata("books/Dune/dune.pdf")      # plain dict
"""
from .api import build_extractor, extract_metadata, get_book_metadata, to_record
from .formats import SUPPORTED_EXTENSIONS, UnsupportedFormat
from .models import FIELDS, BookMetadata, ExtractionResult

__all__ = [
    "get_book_metadata", "extract_metadata", "build_extractor", "to_record", "SUPPORTED_EXTENSIONS", "UnsupportedFormat",
    "FIELDS", "BookMetadata", "ExtractionResult",
]
