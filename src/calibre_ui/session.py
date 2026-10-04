"""Finds (or launches) Calibre and returns its main window page."""
import logging

from calibre_ui.config import UISettings
from calibre_ui.errors import ElementNotFound
from calibre_ui.pages.main_window import MainWindowPage
from calibre_ui.uia.wait import wait_until

log = logging.getLogger(__name__)


def connect(cfg: UISettings) -> MainWindowPage:
    from pywinauto import Application, Desktop

    desktop = Desktop(backend="uia")

    def find():
        return desktop.windows(title_re=cfg.window_title_re)

    windows = find()
    if not windows and cfg.calibre_exe:
        log.info("Calibre not running, starting %s", cfg.calibre_exe)
        Application(backend="uia").start(cfg.calibre_exe)
        windows = wait_until(find, cfg.launch_timeout, interval=1.0, what="the Calibre main window")
    if not windows:
        raise ElementNotFound(
            "Calibre's main window was not found. Start Calibre, or set `calibre_exe` in calibre_ui.yaml "
            f"(title pattern used: {cfg.window_title_re!r})")
    if len(windows) > 1:
        log.warning("%d windows match the Calibre title pattern; using the first", len(windows))
    return MainWindowPage(windows[0], cfg)
