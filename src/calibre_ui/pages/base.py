"""Base class for page objects + a helper to wait for dialog windows."""
from calibre_ui.config import UISettings
from calibre_ui.uia.actions import invoke, is_alive
from calibre_ui.uia.query import find_all, find_one
from calibre_ui.uia.snapshot import Node, snapshot
from calibre_ui.uia.wait import wait_until


class Page:
    """Wraps one window. Subclasses expose actions in the user's language (search, choose, fill...)."""

    def __init__(self, window, cfg: UISettings):
        self.window = window
        self.cfg = cfg

    def nodes(self) -> list[Node]:
        return snapshot(self.window)

    def press(self, name: str, nodes: list[Node] | None = None, *, largest: bool = False) -> None:
        """Press the button whose text is `name` (the biggest one if several share the name)."""
        buttons = find_all(nodes or self.nodes(), type="Button", text=name)
        if not buttons:
            find_one([], f"button {name!r}")  # raises ElementNotFound
        target = max(buttons, key=lambda n: n.rect.area) if largest else buttons[0]
        invoke(target.ctrl)

    def is_open(self) -> bool:
        return is_alive(self.window)

    def wait_closed(self, what: str) -> None:
        # wait_until(lambda: not self.is_open(), self.cfg.dialog_timeout, what=what)
        pass


def wait_for_window(root, match, timeout: float, what: str):
    """Wait for a (dialog) window below `root` for which `match(window)` is true; returns the wrapper."""
    def find():
        for w in root.descendants(control_type="Window"):
            if match(w):
                return w
        return None
    return wait_until(find, timeout, interval=0.3, what=what)
