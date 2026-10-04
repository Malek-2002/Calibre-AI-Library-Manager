"""The algorithm. Talks only to page objects, so it can be tested with fakes (no Windows needed).

  search title+authors -> exact match in the table?
    no  -> Add books -> pick file -> select the new row -> Edit metadata -> write fields -> OK
    yes -> select it -> Edit metadata -> same format already there?  yes: Cancel (skip)
                                                                       no: add format -> OK
"""
import logging
import time
from contextlib import contextmanager, suppress
from pathlib import Path

from calibre_ui.config import UISettings
from calibre_ui.errors import BookDataError, CalibreUIError, UITimeout
from calibre_ui.formats import format_of, has_format
from calibre_ui.matching import find_exact, row_signature
from calibre_ui.models import AddResult, BookDetails, Outcome, TableRow
from calibre_ui.pages.table import added_at
from calibre_ui.search_query import build_query

log = logging.getLogger(__name__)


class AddBookWorkflow:
    def __init__(self, main, cfg: UISettings):
        self.main = main          # a MainWindowPage (or any object with the same methods)
        self.cfg = cfg
        
    def run(self, path: Path | str, details: BookDetails) -> AddResult:
        path = Path(path)
        if not path.is_file():
            raise BookDataError(f"Book file not found: {path}")
        fmt = format_of(path)
        if not fmt:
            raise BookDataError(f"Cannot tell the book format from {path.name!r} (no file extension)")

        existing = self._find_existing(details)
        if existing is None:
            log.info("%r not in Calibre -> adding the book", details.title)
            result = self._add_new(path, fmt, details)
        else:
            log.info("%r already in Calibre -> checking formats", details.title)
            result = self._add_format(existing, path, fmt, details)
        
        if self.cfg.verify_after_save and result.outcome is not Outcome.SKIPPED:
            result.verified = self._find_existing(details) is not None
        self.main.clear_search()
        return result

    # ---- step 1: is it already there? ----
    def _find_existing(self, details: BookDetails) -> TableRow | None:
        rows = self.main.search(build_query(details, self.cfg.search_mode))
        return find_exact(rows, details, self.cfg)

    # ---- new book ----
    def _add_new(self, path: Path, fmt: str, details: BookDetails) -> AddResult:
        self.main.clear_search()  # the new book must not be hidden by the current search
        before = {row_signature(r) for r in self.main.rows()}
        self.main.open_add_books().choose(path)
        row = self._wait_for_new_row(before)
        self.main.select_row(row)

        with self._editing() as edit:
            # edit.assert_single()
            if not has_format(edit.formats(), fmt):
                raise CalibreUIError(f"The opened book has no {fmt} file: the wrong book was selected")
            report = edit.fill(details)
            edit.ok()
        return AddResult(Outcome.ADDED, fmt, report.applied, report.failed)

    def _wait_for_new_row(self, before: set) -> TableRow:
        deadline = time.monotonic() + self.cfg.add_timeout
        while time.monotonic() < deadline:
            new = [r for r in self.main.rows(selection=True) if row_signature(r) not in before]
            if row := self._pick_new(new):
                return row
            time.sleep(0.5)
        raise UITimeout("The added book did not show up in the list (was it rejected as a duplicate?)")

    def _pick_new(self, new: list[TableRow]) -> TableRow | None:
        if len(new) == 1:
            return new[0]
        selected = [r for r in new if r.selected]       # Calibre selects books it just added
        if len(selected) == 1:
            return selected[0]
        dated = [(added_at(r, self.cfg.t("col_date")), r) for r in new]
        dated = [(d, r) for d, r in dated if d]
        if dated:                                        # otherwise the most recently added
            newest = max(d for d, _ in dated)
            top = [r for d, r in dated if d == newest]
            if len(top) == 1:
                return top[0]
        return None

    # ---- existing book ----
    def _add_format(self, row: TableRow, path: Path, fmt: str, details: BookDetails) -> AddResult:
        self.main.select_row(row)
        with self._editing() as edit:
            if has_format(edit.formats(), fmt):
                edit.cancel()
                return AddResult(Outcome.SKIPPED, fmt)
            edit.add_format(path)
            edit.ok()
        return AddResult(Outcome.FORMAT_ADDED, fmt)

    @contextmanager
    def _editing(self):
        """Open Edit metadata; if anything fails, close the dialog so Calibre is not left blocked."""
        edit = self.main.open_edit_metadata()
        try:
            yield edit
        except Exception:
            with suppress(Exception):
                if edit.is_open():
                    edit.cancel()
            raise
