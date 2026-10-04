"""Public entry points. Use get_book_metadata() from other code / UI automation."""
from pathlib import Path
from typing import Any, Callable

try:  # load E:\Calibre\.env (OCR_API_KEY, TESSERACT_CMD, ...) even when main.py is not the caller
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

from .formats import get_extractor  # noqa: E402  (after .env is loaded)
from .models import ExtractionResult  # noqa: E402

RECORD_FIELDS = (
    "title", "authors", "file_size", "rating", "tags",
    "series", "publisher", "publish_date", "comments", "isbn",
)


def _llm_disabled(*_args: Any, **_kwargs: Any):
    raise RuntimeError("LLM disabled (use_llm=False)")


def build_extractor(
    path: Path | str,
    *,
    model: str | None = None,
    scrape: bool | None = None,
    use_llm: bool = True,
    pages: int = 0,
    ask_fn: Callable[..., Any] | None = None,
):
    """Create the right extractor for the file with the given options.

    scrape: None = default (on, unless SCRAPE_DISABLED=1 in .env), False = off.
    """
    kwargs: dict[str, Any] = {"model": model}
    if not use_llm:
        kwargs["ask_fn"] = _llm_disabled
    elif ask_fn is not None:
        kwargs["ask_fn"] = ask_fn
    extractor = get_extractor(path, **kwargs)
    if not use_llm:
        extractor.identify_first = False  # nothing to ask; use the embedded title/authors
    if pages:
        extractor.pages = pages
    if scrape is not None:
        extractor.scrape = scrape
    return extractor


def extract_metadata(path: Path | str, **options: Any) -> ExtractionResult:
    """Full result object (metadata + provenance + raw scraped/LLM data). Options: see build_extractor."""
    return build_extractor(path, **options).extract()


def to_record(res: ExtractionResult) -> dict:
    """Flatten an ExtractionResult into the plain dict handed to other code."""
    m = res.metadata
    record = {"path": str(res.path)}
    record.update({name: getattr(m, name) for name in RECORD_FIELDS})
    record.update(
        missing=res.missing,              # fields nobody could fill
        complete=res.complete,
        text_source=res.text_source,      # text | ocr | mixed | none
        sources=dict(m.sources),          # field -> embedded | goodreads | amazon | llm | file | text | ocr
        errors=list(res.errors),
    )
    return record


def get_book_metadata(path: Path | str, **options: Any) -> dict:
    """Book path -> metadata dict.

        {
          "path": "...", "title": "Wool", "authors": ["Hugh Howey"], "file_size": 2345550,
          "rating": 4.07, "tags": [...], "series": "Silo #1", "publisher": "Century",
          "publish_date": "Jun 2011", "comments": "...", "isbn": "9780...",
          "missing": [], "complete": True, "text_source": "mixed",
          "sources": {"title": "embedded", "rating": "goodreads", ...}, "errors": []
        }

    Empty values are "" / [] / 0 (never None). Individual failures (OCR, a site that
    blocks us, an LLM error) never raise: they end up in "errors" and the pipeline
    keeps going with what it has.
    Raises only FileNotFoundError (bad path) and UnsupportedFormat (e.g. .epub for now).

    Options: model=<llm.yaml profile>, scrape=False, use_llm=False, pages=<n>.
    """
    return to_record(extract_metadata(path, **options))
