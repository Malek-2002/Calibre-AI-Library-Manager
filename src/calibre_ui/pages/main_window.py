"""Calibre's main window: search box, book list, toolbar."""
import time

from calibre_ui.config import UISettings
from calibre_ui.errors import ElementNotFound
from calibre_ui.models import TableRow
from calibre_ui.pages.base import Page
from calibre_ui.pages.edit_metadata import EditMetadataPage
from calibre_ui.pages.file_dialog import FileDialogPage
from calibre_ui.pages.table import parse_rows
from calibre_ui.uia.actions import invoke, is_selected, set_text
from calibre_ui.uia.query import find_all, find_one, largest


class MainWindowPage(Page):
    def focus(self) -> None:
        try:
            self.window.restore()
        except Exception:
            pass
        self.window.set_focus()

    # ---- search ----
    def search(self, query: str) -> list[TableRow]:
        """Run a Calibre search and return the rows that remain once the table has settled."""
        self.focus()
        nodes = self.nodes()
        button = find_one(nodes, "the Search button", type="Button", text=self.cfg.t("search"))
        # the search box = the widest Edit on the same row, to the left of the Search button
        same_row = [e for e in find_all(nodes, type="Edit")
                    if e.rect.right <= button.rect.left + 2 and abs(e.rect.cy - button.rect.cy) <= button.rect.height]
        if not same_row:
            raise ElementNotFound("Could not find Calibre's search box")
        set_text(largest(same_row).ctrl, query, match="exact", commit=False, pause=self.cfg.key_pause)
        invoke(button.ctrl)
        time.sleep(0.3)
        return self._settled_rows()

    def clear_search(self) -> list[TableRow]:
        return self.search("")

    # ---- table ----
    def rows(self, *, selection: bool = False) -> list[TableRow]:
        rows = parse_rows(self.nodes())
        if selection:
            for r in rows:
                r.selected = is_selected(r.click_node.ctrl)
        return rows

    def _settled_rows(self) -> list[TableRow]:
        """Read the table until two consecutive reads agree (the view refreshes asynchronously)."""
        time.sleep(self.cfg.search_settle)
        last = None
        deadline = time.monotonic() + self.cfg.action_timeout
        while True:
            rows = self.rows()
            sig = [tuple(sorted(r.values.items())) for r in rows]
            if sig == last or time.monotonic() >= deadline:
                return rows
            last = sig
            time.sleep(self.cfg.search_settle / 2)

    def select_row(self, row: TableRow) -> None:
        """Click the row so it is the only selected book."""
        self.focus()
        row.click_node.ctrl.click_input()
        time.sleep(0.3)

    # ---- toolbar actions that open dialogs ----
    def open_add_books(self) -> FileDialogPage:
        self.press(self.cfg.t("add_books"))
        return FileDialogPage.wait(self.window, self.cfg)

    def open_edit_metadata(self) -> EditMetadataPage:
        self.press(self.cfg.t("edit_metadata"))
        return EditMetadataPage.wait(self.window, self.cfg)