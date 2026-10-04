"""The standard Windows 'Open' dialog, used both for 'Add books' and for 'Add format'."""
from pathlib import Path

from calibre_ui.config import UISettings
from calibre_ui.pages.base import Page, wait_for_window
from calibre_ui.uia.actions import set_text
from calibre_ui.uia.query import field_for_label


class FileDialogPage(Page):
    @classmethod
    def wait(cls, root, cfg: UISettings) -> "FileDialogPage":
        label = cfg.t("file_name")

        def is_file_dialog(w) -> bool:
            return any((c.window_text() or "").strip() == label for c in w.descendants(control_type="Text"))

        return cls(wait_for_window(root, is_file_dialog, cfg.dialog_timeout, "the file selection dialog"), cfg)

    def choose(self, path: Path | str) -> None:
        """Type the full path into 'File name' and press Open."""
        nodes = self.nodes()
        edit = field_for_label(nodes, self.cfg.t("file_name"), types=("Edit", "ComboBox"))
        set_text(edit.ctrl, str(Path(path)), match="exact", pause=self.cfg.key_pause)
        self.press(self.cfg.t("open"), nodes, largest=True)  # several tiny 'Open' buttons exist; take the real one
        self.wait_closed("the file dialog to close")
