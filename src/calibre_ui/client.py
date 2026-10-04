"""Public API."""
import logging
from pathlib import Path
from typing import Any

from calibre_ui.config import UISettings, load_settings
from calibre_ui.models import AddResult, BookDetails
from calibre_ui.session import connect
from calibre_ui.workflow import AddBookWorkflow

log = logging.getLogger(__name__)


class CalibreClient:
    """Drives a running Calibre through its UI. Connects lazily and reuses the connection."""

    def __init__(self, settings: UISettings | None = None):
        self.cfg = settings or load_settings()
        self._main = None

    @property
    def main(self):
        if self._main is None:
            self._main = connect(self.cfg)
        return self._main

    def add_book(self, path: Path | str, details: Any) -> AddResult:
        """Add `path` to Calibre (new book / extra format / skip) using `details` as its metadata.

        `details` may be a BookDetails, a dict, or any object with title, authors, rating, tags, series,
        publisher, publish_date, isbn and comments attributes (e.g. the metadata extraction result).
        """
        book = details if isinstance(details, BookDetails) else BookDetails.from_any(details)
        return AddBookWorkflow(self.main, self.cfg).run(path, book)


def add_to_calibre(path: Path | str, details: Any, *, settings: UISettings | None = None) -> AddResult:
    return CalibreClient(settings).add_book(path, details)
