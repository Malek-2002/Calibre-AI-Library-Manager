"""The shared algorithm. A format only implements read_embedded() and read_front_text().

Pipeline:
  1. embedded metadata + file size; implausible embedded values are REJECTED (see trust.py)
     so that they count as missing instead of poisoning the result
  2. text of the first pages (text layer / OCR)
  3. ISBN printed in the text (checksum verified)
  4. the LLM IDENTIFIES the book: title + authors (these replace the embedded values,
     which are often truncated or junk)
  5. scrape Goodreads, then Amazon with that title/authors. SCRAPED DATA WINS: it replaces
     whatever the embedded metadata / identification said, field by field. The first site
     that provides a field decides it (Goodreads before Amazon). Exceptions: file_size, and an
     ISBN that is printed in the book itself (it identifies THIS edition).
  6. LLM completion only for fields that are still missing
Steps 3 and 6 only fill empty fields. Set `scraped_wins = False` for the old "scraping only fills
gaps" behaviour.
"""
import difflib
import logging
import os
import re
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .cleaning import sanitize
from .isbn import find_isbn
from .models import FIELDS, BookMetadata, ExtractionResult
from .prompt import IDENTITY_SCHEMA, METADATA_SCHEMA, build_identify_prompt, build_prompt
from .trust import date_reason, distrust_embedded
from .validation import clean_identity_record, clean_llm_record

log = logging.getLogger(__name__)

# Legitimately empty for standalone books: never worth an LLM call on its own.
OPTIONAL_FIELDS = {"series"}

# An ISBN with one of these sources was read from the book itself and is never replaced by a scraped one.
PRINTED_ISBN_SOURCES = {"text", "ocr", "mixed", "embedded"}


# --------------------------------------------------------------------------- #
# helpers for judging scraped results
# --------------------------------------------------------------------------- #
def _title_key(title: str) -> str:
    """'Dust (Silo, #3)' / 'Dust: A Novel' -> 'dust'."""
    title = re.sub(r"\s*\([^)]*\)\s*$", "", title)
    return re.sub(r"[\W_]+", " ", title.split(":")[0]).strip().casefold()


def _surnames(names: list[str]) -> set[str]:
    return {n.split()[-1].casefold().strip(".,") for n in names if n and n.split()}


def _same_book(meta: BookMetadata, found: dict[str, Any]) -> bool:
    """Guard against a scraper returning a different book (we let its data replace ours)."""
    their_title, their_authors = found.get("title"), found.get("authors")
    if their_title and meta.title:
        a, b = _title_key(str(their_title)), _title_key(meta.title)
        if a and b and not (a == b or a.startswith(b) or b.startswith(a)
                            or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8):
            return False
    if their_authors and meta.authors:
        if not _surnames(list(their_authors)) & _surnames(meta.authors):
            return False
    return True


def _clean_scraped(name: str, value: Any) -> Any:
    if name == "title" and isinstance(value, str):  # Goodreads style "Dust (Silo, #3)" -> "Dust"
        return re.sub(r"\s*\([^)]*#\s*\d+[^)]*\)\s*$", "", value).strip()
    return value


def _blank(like: Any) -> Any:
    return [] if isinstance(like, list) else "" if isinstance(like, str) else None


class BookMetadataExtractor(ABC):
    pages = 3                  # how many leading pages are read / OCR'd
    max_prompt_chars = 6000    # excerpt size sent to the LLM
    min_confidence = 0.4       # below this an LLM answer is discarded
    identify_first = True      # always let the LLM establish title + authors first
    scraped_wins = True        # scraped values replace embedded / identified ones (False = only fill gaps)
    scrape = os.getenv("SCRAPE_DISABLED", "").lower() not in {"1", "true", "yes"}

    def __init__(
        self,
        path: Path | str,
        *,
        ask_fn: Callable[..., Any] | None = None,
        model: str | None = None,
    ):
        self.path = Path(path)
        self.ask_fn = ask_fn
        self.model = model

    # ---- implemented per format ------------------------------------------ #
    @abstractmethod
    def read_embedded(self) -> BookMetadata:
        """Metadata declared inside the file itself."""

    @abstractmethod
    def read_front_text(self) -> tuple[str, str]:
        """Text of the first `self.pages` pages -> (text, source), source in text|ocr|mixed|none."""

    # ---- shared ----------------------------------------------------------- #
    @staticmethod
    def _needed(meta: BookMetadata) -> list[str]:
        return [f for f in meta.missing() if f not in OPTIONAL_FIELDS]

    def extract(self) -> ExtractionResult:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        errors: list[str] = []

        # 1. embedded metadata + file size
        try:
            meta = self.read_embedded()
        except Exception as e:
            log.warning("embedded metadata unreadable for %s: %s", self.path, e)
            errors.append(f"embedded: {e}")
            meta = BookMetadata()
        sanitize(meta, self.path.stem)
        for rejection in distrust_embedded(meta, self.path, assume_all_embedded=True):
            log.info("embedded value rejected for %s: %s", self.path.name, rejection)
            errors.append(f"embedded rejected: {rejection}")
        meta.file_size = self.path.stat().st_size
        meta.sources["file_size"] = "file"

        # 2. first pages (text layer, or OCR)
        try:
            text, source = self.read_front_text()
        except Exception as e:
            log.warning("front text unreadable for %s: %s", self.path, e)
            errors.append(f"text: {e}")
            text, source = "", "none"

        # 3. ISBN printed in the book
        meta.fill("isbn", find_isbn(text), source)

        result = ExtractionResult(self.path, meta, text_source=source, errors=errors)
        excerpt = text[: self.max_prompt_chars]

        # 4. LLM identifies the book (title + authors); falls back to the embedded values
        if self.identify_first or not (meta.isbn or (meta.title and meta.authors)):
            self._identify(result, excerpt, source)

        # 5. scrape Goodreads / Amazon (always: scraped data replaces weaker values)
        if self.scrape and (self.scraped_wins or self._needed(meta)):
            self._scrape(result)

        # 6. LLM completion for whatever is still missing
        if self._needed(meta):
            self._complete_with_llm(result, excerpt, source)
        return result

    # ---- step 4 ------------------------------------------------------------ #
    def _identify(self, result: ExtractionResult, excerpt: str, source: str) -> None:
        meta = result.metadata
        prompt = build_identify_prompt(self.path.name, meta, excerpt, source)
        try:
            ident = clean_identity_record(self._ask(prompt, IDENTITY_SCHEMA))
        except Exception as e:
            log.warning("identify failed for %s: %s", self.path, e)
            result.errors.append(f"identify: {e}")
            return
        result.identity = ident or None
        if not ident or ident["confidence"] < self.min_confidence:
            result.errors.append("identify: book not recognised with enough confidence")
            return
        if ident["title"]:  # the LLM saw the title page: it replaces the embedded value
            meta.title, meta.sources["title"] = ident["title"], "llm"
        if ident["authors"]:
            meta.authors, meta.sources["authors"] = ident["authors"], "llm"
        meta.fill("isbn", ident["isbn"], "llm")

    # ---- step 5 ------------------------------------------------------------ #
    @staticmethod
    def _override(meta: BookMetadata, name: str, value: Any, source: str) -> bool:
        """Replace a field through meta.fill() (so its normalisation/validation still applies).
        If fill() rejects the new value, the old one is restored. Returns True if the field was set."""
        old, old_source = getattr(meta, name, None), meta.sources.get(name)
        setattr(meta, name, _blank(old))
        meta.sources.pop(name, None)
        meta.fill(name, value, source)
        if name in meta.missing():
            setattr(meta, name, old)
            if old_source is not None:
                meta.sources[name] = old_source
            return False
        return True

    @staticmethod
    def _fill_gap(meta: BookMetadata, name: str, value: Any, source: str) -> bool:
        if name not in meta.missing():
            return False
        meta.fill(name, value, source)
        return name not in meta.missing()

    def _scrape(self, result: ExtractionResult) -> None:
        meta = result.metadata
        if not (meta.isbn or (meta.title and meta.authors)):
            result.errors.append("scrape: skipped, need an ISBN or title + authors to search")
            return
        try:
            from scrapers import iter_sources  # lazy: avoids an import cycle with metadata
        except ImportError as e:
            result.errors.append(f"scrape: {e}")
            return

        protected = {"file_size"}
        if meta.sources.get("isbn") in PRINTED_ISBN_SOURCES and meta.isbn:
            protected.add("isbn")                      # the ISBN printed in this very file wins
        wanted = set(FIELDS) - OPTIONAL_FIELDS - protected
        done: set[str] = set()                         # fields already decided by a scraper

        try:
            for book in iter_sources(title=meta.title, authors=meta.authors, isbn=meta.isbn):
                result.scraped.append(book.to_dict())
                found = {k: _clean_scraped(k, v) for k, v in book.fields().items()
                         if v not in (None, "", [], 0)}
                if self.scraped_wins and not _same_book(meta, found):
                    result.errors.append(f"scrape: {book.source} returned a different book, ignored")
                    continue
                for name, value in found.items():
                    if name in protected or name in done:
                        continue
                    if name == "publish_date" and date_reason(value, date.today()):
                        continue                       # never trade one bad date for another
                    ok = (self._override(meta, name, value, book.source) if self.scraped_wins
                          else self._fill_gap(meta, name, value, book.source))
                    if ok:
                        done.add(name)
                if wanted <= done or (not self.scraped_wins and not self._needed(meta)):
                    break                              # complete: do not bother the next site
        except Exception as e:                         # a failing site must not kill the extraction
            log.warning("scraping failed for %s: %s", self.path, e)
            result.errors.append(f"scrape: {e}")

    # ---- step 6 ------------------------------------------------------------ #
    def _complete_with_llm(self, result: ExtractionResult, excerpt: str, source: str) -> None:
        meta, errors = result.metadata, result.errors
        prompt = build_prompt(self.path.name, meta, meta.missing(), excerpt, source)
        try:
            raw = self._ask(prompt, METADATA_SCHEMA)
        except Exception as e:
            log.warning("LLM failed for %s: %s", self.path, e)
            errors.append(f"llm: {e}")
            return

        result.llm_used = True
        result.llm_raw = raw if isinstance(raw, dict) else {"_raw": raw}
        rec = clean_llm_record(raw)
        if not rec:
            errors.append("llm: answer was not a JSON object")
            return
        result.llm_confidence = rec["confidence"]
        if rec["confidence"] < self.min_confidence:
            errors.append(f"llm: confidence {rec['confidence']:.2f} < {self.min_confidence}, answer ignored")
            return
        for name in FIELDS:
            meta.fill(name, rec[name], "llm")

    def _ask(self, prompt: str, schema: dict) -> Any:
        ask_fn = self.ask_fn
        if ask_fn is None:
            from llm import ask  # lazy import
            ask_fn = ask
        kwargs: dict[str, Any] = {"schema": schema, "parse_json": True}
        if self.model:
            kwargs["model"] = self.model
        return ask_fn(prompt, **kwargs)