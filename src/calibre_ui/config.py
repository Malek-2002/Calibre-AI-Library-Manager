"""Settings for the Calibre UI automation (config/calibre_ui.yaml, all keys optional)."""
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

from calibre_ui.errors import CalibreUIError

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config" / "calibre_ui.yaml"

# Every piece of text we look for in Calibre's UI, in one place (override in YAML for other languages).
DEFAULT_UI_TEXT = {
    # main window
    "add_books": "Add books", "edit_metadata": "Edit metadata", "search": "Search",
    "col_title": "Title", "col_authors": "Author(s)", "col_date": "Date",
    # dialogs
    "ok": "OK", "cancel": "Cancel", "open": "Open", "file_name": "File name:", "comments_group": "Comments",
    # edit-metadata field labels
    "title": "Title:", "authors": "Author(s):", "series": "Series:", "series_index": "Number:",
    "rating": "Rating:", "tags": "Tags:", "identifiers": "Ids:", "published": "Published:",
    "publisher": "Publisher:",
}

ADD_FORMAT_BUTTONS = {"auto", "top_left", "top_right", "bottom_left", "bottom_right"}


@dataclass
class UISettings:
    calibre_exe: str | None = None
    window_title_re: str = r"^calibre\s*[\u2014\u2013-]\s*\|\|"
    edit_dialog_title_re: str = r"^Edit metadata"
    launch_timeout: float = 60
    dialog_timeout: float = 20
    action_timeout: float = 10
    add_timeout: float = 90
    search_mode: str = "loose"
    search_settle: float = 0.6
    date_format: str = "%b %Y"
    add_format_button: str = "auto"
    skip_fields: list[str] = field(default_factory=list)
    verify_after_save: bool = True
    key_pause: float = 0.01
    ui_text: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        self.ui_text = {**DEFAULT_UI_TEXT, **(self.ui_text or {})}
        if self.search_mode not in ("loose", "exact"):
            raise CalibreUIError("search_mode must be 'loose' or 'exact'")
        if self.add_format_button not in ADD_FORMAT_BUTTONS:
            raise CalibreUIError(f"add_format_button must be one of {sorted(ADD_FORMAT_BUTTONS)}")

    def t(self, key: str) -> str:
        """UI text by key, e.g. cfg.t('add_books')."""
        return self.ui_text[key]


def load_settings(path: Path | str | None = None) -> UISettings:
    path = Path(path or os.environ.get("CALIBRE_UI_CONFIG") or DEFAULT_CONFIG_PATH)
    if not path.exists():
        return UISettings()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    known = {f.name for f in fields(UISettings)}
    unknown = set(raw) - known
    if unknown:
        raise CalibreUIError(f"Unknown key(s) in {path}: {sorted(unknown)}. Valid: {sorted(known)}")
    return UISettings(**raw)
