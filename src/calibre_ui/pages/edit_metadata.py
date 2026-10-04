"""Calibre's 'Edit metadata' dialog: write fields, add a format, OK / Cancel."""
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from calibre_ui import fields as fmt
from calibre_ui.config import UISettings
from calibre_ui.errors import CalibreUIError, ElementNotFound, FieldError
from calibre_ui.formats import has_format, parse_format_item
from calibre_ui.models import BookDetails, FillReport
from calibre_ui.pages.base import Page, wait_for_window
from calibre_ui.pages.file_dialog import FileDialogPage
from calibre_ui.uia.actions import combo_item_count, help_text, select_combo_index, set_date, set_text
from calibre_ui.uia.query import field_for_label, find_all, largest
from calibre_ui.uia.snapshot import Node
from calibre_ui.uia.wait import wait_until


@dataclass(frozen=True)
class FieldSpec:
    name: str                                                   # also used in skip_fields / reports
    label_key: str | None                                       # key into cfg.ui_text (None = special lookup)
    kind: str                                                   # text | number | date | rating | comments
    value: Callable[[BookDetails, UISettings], object]          # None / empty -> field is left alone


# Order matters: setting the series can auto-fill its number, so the number is written after it.
FIELD_SPECS = [
    FieldSpec("title", "title", "text", lambda d, c: d.title),
    FieldSpec("authors", "authors", "text", lambda d, c: fmt.join_authors(d.authors)),
    FieldSpec("series", "series", "text", lambda d, c: d.series),
    FieldSpec("series_index", "series_index", "number",
              lambda d, c: f"{d.series_index:.2f}" if d.series and d.series_index is not None else None),
    FieldSpec("rating", "rating", "rating", lambda d, c: d.rating),
    FieldSpec("tags", "tags", "text", lambda d, c: fmt.join_tags(d.tags)),
    FieldSpec("isbn", "identifiers", "text", lambda d, c: fmt.identifiers(d.isbn)),
    FieldSpec("publish_date", "published", "date", lambda d, c: fmt.format_pubdate(d.publish_date, c.date_format)),
    FieldSpec("publisher", "publisher", "text", lambda d, c: d.publisher),
    FieldSpec("comments", None, "comments", lambda d, c: d.comments),
]


class EditMetadataPage(Page):
    @classmethod
    def wait(cls, root, cfg: UISettings) -> "EditMetadataPage":
        rx = re.compile(cfg.edit_dialog_title_re)
        win = wait_for_window(root, lambda w: bool(rx.search(w.window_text() or "")), cfg.dialog_timeout,
                              "the Edit metadata dialog (is exactly one book selected?)")
        return cls(win, cfg)

    # ---- reading ----
    @property
    def title(self) -> str:
        return self.window.window_text() or ""

    def formats(self) -> list[str]:
        """Formats already attached to the book, e.g. ['EPUB'] (read from the 'EPUB (0.78 MB)' list)."""
        items = find_all(self.nodes(), type="ListItem")
        return [f for f in (parse_format_item(i.text) for i in items) if f]
   
    # ---- writing ----
    def fill(self, details: BookDetails) -> FillReport:
        """Write every available field. A field that fails is reported, the others still get written."""
        nodes = self.nodes()
        report = FillReport()
        writers = {"text": self._write_text, "number": self._write_number, "date": self._write_date,
                   "rating": self._write_rating, "comments": self._write_comments}
        for spec in FIELD_SPECS:
            value = spec.value(details, self.cfg)
            if spec.name in self.cfg.skip_fields or value in (None, "", []):
                continue
            try:
                node = self._locate(nodes, spec)
                writers[spec.kind](node, value)
                report.applied.append(spec.name)
            except (FieldError, ElementNotFound) as e:
                report.failed[spec.name] = str(e)
            except Exception as e:  # any other UI hiccup on one field must not lose the remaining fields
                report.failed[spec.name] = f"{type(e).__name__}: {e}"
        return report

    def _locate(self, nodes: list[Node], spec: FieldSpec) -> Node:
        if spec.label_key:
            return field_for_label(nodes, self.cfg.t(spec.label_key))
        groups = find_all(nodes, type="Group", text=self.cfg.t("comments_group"))
        if not groups:
            raise ElementNotFound("Comments group not found")
        editors = find_all(nodes, type="Edit", within=groups[0].rect)
        if not editors:
            raise ElementNotFound("Comments editor not found")
        return largest(editors)

    def _write_text(self, node: Node, value) -> None:
        set_text(node.ctrl, str(value), match="exact", pause=self.cfg.key_pause)

    def _write_number(self, node: Node, value) -> None:
        set_text(node.ctrl, str(value), match="number", pause=self.cfg.key_pause)

    def _write_date(self, node: Node, value) -> None:
        set_date(node.ctrl, str(value), pause=self.cfg.key_pause, label="published")
     
    def _write_comments(self, node: Node, value) -> None:
        set_text(node.ctrl, str(value), match="lenient", commit=False, pause=self.cfg.key_pause)

    def _write_rating(self, node: Node, value) -> None:
        idx = fmt.rating_to_index(float(value), combo_item_count(node.ctrl))
        if idx is None:
            return
        try:
            select_combo_index(node.ctrl, idx)
        except Exception as e:
            raise FieldError(f"could not select rating item {idx}: {e}") from e

    # ---- formats ----
    def add_format(self, path: Path | str) -> None:
        """Press 'add format', pick the file, and wait until the format shows in the list."""
        from calibre_ui.formats import format_of
        wanted = format_of(path)
        print("in add format button")
        self._add_format_button().ctrl.click_input()
        FileDialogPage.wait(self.window, self.cfg).choose(path)
        wait_until(lambda: has_format(self.formats(), wanted), self.cfg.dialog_timeout,
                   what=f"format {wanted} to appear in the book's format list")

    def _add_format_button(self) -> Node:
        """The '+' button next to the formats list. Identified by tooltip; position is the fallback."""
        nodes = self.nodes()
        lists = find_all(nodes, type="List")
        if not lists:
            raise ElementNotFound("Formats list not found")
        # smallest group that contains the list = the formats box
        boxes = [g for g in find_all(nodes, type="Group") if g.rect.contains(lists[0].rect)]
        box = min(boxes, key=lambda g: g.rect.area)
        buttons = sorted(find_all(nodes, type="Button", within=box.rect), key=lambda b: (b.rect.top, b.rect.left))
        if len(buttons) < 2:
            raise ElementNotFound("Format buttons not found")

        mode = self.cfg.add_format_button
        if mode == "auto":
            for b in buttons:  # tooltip e.g. "Add a new format for this book to the calibre library"
                h = help_text(b.ctrl).lower()
                if "add" in h and "format" in h:
                    return b
            mode = "top_right"
        left, right = min(b.rect.left for b in buttons), max(b.rect.left for b in buttons)
        top, bottom = min(b.rect.top for b in buttons), max(b.rect.top for b in buttons)
        want_x, want_y = {"top_left": (left, top), "top_right": (right, top),
                          "bottom_left": (left, bottom), "bottom_right": (right, bottom)}[mode]
        return next(b for b in buttons if b.rect.left == want_x and b.rect.top == want_y)

    # ---- closing ----
    def ok(self) -> None:
        self.press(self.cfg.t("ok"))
        self.wait_closed("the Edit metadata dialog to close after saving")

    def cancel(self) -> None:
        self.press(self.cfg.t("cancel"))
        time.sleep(0.2)
        if self.is_open():  # Calibre may ask to confirm discarding changes
            self.press(self.cfg.t("cancel"))
        self.wait_closed("the Edit metadata dialog to close")
