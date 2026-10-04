"""Web scrapers that complete book metadata from Goodreads and Amazon.

    from scrapers import iter_sources
    for book in iter_sources(title="Wool", authors=["Hugh Howey"], isbn=""):
        print(book.source, book.rating, book.tags)

.env:  SCRAPE_SOURCES=goodreads,amazon   (order = priority; default both)
"""
import logging
import os
from typing import Iterator

from . import amazon, goodreads
from .http import Blocked, NotFound, ScrapeError
from .models import ScrapedBook

log = logging.getLogger(__name__)

SOURCES = {"goodreads": goodreads.lookup, "amazon": amazon.lookup}


def enabled_sources() -> list[str]:
    names = (os.getenv("SCRAPE_SOURCES") or "goodreads,amazon").split(",")
    return [n.strip().lower() for n in names if n.strip().lower() in SOURCES]


def iter_sources(
    title: str = "", authors: list[str] | None = None, isbn: str = "",
    sources: list[str] | None = None,
) -> Iterator[ScrapedBook]:
    """Yield one ScrapedBook per source that found the book, lazily and in priority order.

    Lazy on purpose: the caller stops iterating once nothing is missing, so the
    next site is never contacted. An ISBN learned from one site feeds the next.
    """
    authors = authors or []
    for name in sources or enabled_sources():
        try:
            book = SOURCES[name](title=title, authors=authors, isbn=isbn)
        except ScrapeError as e:  # blocked / network / not found: try the next source
            log.warning("scrape %s: %s", name, e)
            continue
        except Exception:
            log.exception("scrape %s crashed (parser out of date?)", name)
            continue
        if book is None:
            log.info("scrape %s: no confident match", name)
            continue
        isbn = isbn or book.isbn
        yield book


__all__ = ["iter_sources", "enabled_sources", "ScrapedBook", "ScrapeError", "Blocked", "NotFound"]
