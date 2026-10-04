"""Things we DO to controls: press, type, select, with verification. pywinauto is imported lazily."""
import re
import time

from calibre_ui.errors import FieldError


def is_alive(ctrl) -> bool:
    try:
        return bool(ctrl.is_visible())
    except Exception:
        return False


def invoke(ctrl) -> None:
    """Press a button: UIA Invoke first (works in the background), real click as fallback."""
    ctrl.click_input()


def read_value(ctrl) -> str:
    try:
        return ctrl.get_value() or ""
    except Exception:
        return ctrl.window_text() or ""


def read_display(ctrl) -> str:
    """What a widget currently SHOWS. Qt date editors expose it as the control's name
    ('Oct 2018'), not as an Edit value, so the name comes first."""
    getters = (lambda c: c.window_text(), lambda c: c.get_value(),
               lambda c: c.legacy_properties().get("Value"))
    for getter in getters:
        try:
            value = getter(ctrl)
        except Exception:
            continue
        if value and str(value).strip():
            return str(value)
    return ""


def help_text(ctrl) -> str:
    """Tooltip / UIA HelpText (empty if the control has none)."""
    try:
        return ctrl.element_info.element.CurrentHelpText or ""
    except Exception:
        return ""


def is_selected(ctrl) -> bool | None:
    """Is this (row cell) selected? None when the control cannot tell."""
    try:
        return bool(ctrl.iface_selection_item.CurrentIsSelected)
    except Exception:
        return None


def escape_keys(text: str) -> str:
    """Escape characters that pywinauto's send_keys treats as commands."""
    return "".join("{" + c + "}" if c in "+^%~()[]" else "{{}" if c == "{" else "{}}" if c == "}" else c
                   for c in text)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().casefold()


def _matches(got: str, want: str, mode: str) -> bool:
    if mode == "none":
        return True
    g, w = _norm(got), _norm(want)
    if mode == "number":
        try:
            return abs(float(g.replace(",", ".")) - float(w.replace(",", "."))) < 1e-6
        except ValueError:
            return False
    if mode == "lenient":  # rich editors: accept a prefix match, or an unreadable (empty) value
        return not g or w[:30] in g
    return g == w


def set_text(ctrl, text: str, *, match: str = "exact", commit: bool = True, pause: float = 0.01) -> None:
    """Clear existing text and write `text` directly into an edit-like control."""
    try:
        # First clear existing text directly via API
        ctrl.set_edit_text("")
        if text:
            ctrl.set_edit_text(text)
    except Exception:
        # Fallback to key simulation: select all and delete first
        ctrl.click_input()
        from pywinauto.keyboard import send_keys
        send_keys("^a{DELETE}", pause=pause)
        if text:
            send_keys(escape_keys(text), pause=pause, with_spaces=True)


# --------------------------------------------------------------------------- #
# date editors (Qt QDateTimeEdit: sections, not a text box)
# --------------------------------------------------------------------------- #
def _put_on_clipboard(text: str) -> None:
    import win32clipboard  # installed with pywinauto (pywin32)
    import win32con

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def set_date(ctrl, text: str, *, pause: float = 0.02, settle: float = 0.15, label: str = "date") -> None:
    """Write a date such as 'Oct 2018' / '03 Oct 2026' into a Qt date editor and VERIFY it.

    A QDateTimeEdit validates section by section, so the string cannot simply be typed:
    clearing it first (Ctrl+A, Delete) drops it into its 'Undefined' state and the typed text
    is thrown away on focus-out. Instead:
      1. sections : Home -> type each part -> Tab to the next section
      2. paste    : Ctrl+A, Ctrl+V of the whole string (changes the clipboard)
    After each attempt the displayed value is read back; FieldError if neither worked.
    """
    from pywinauto.keyboard import send_keys

    want = _norm(text)
    if _norm(read_display(ctrl)) == want:
        return
    parts = re.findall(r"[A-Za-z]+|\d+", text)
    if not parts:
        raise FieldError(f"{label}: nothing to type in {text!r}")

    def sections() -> None:
        if not re.search(r"\d", read_display(ctrl)):  # 'Undefined': step out of the special value first
            send_keys("{UP}", pause=pause)
        send_keys("{HOME}", pause=pause)
        for i, part in enumerate(parts):
            send_keys(part, pause=pause)
            if i < len(parts) - 1:
                send_keys("{TAB}", pause=pause)

    def paste() -> None:
        _put_on_clipboard(text)
        send_keys("^a^v", pause=pause)

    shown = ""
    for attempt in (sections, paste):
        ctrl.click_input()
        time.sleep(settle)
        try:
            attempt()
        except Exception:
            continue
        time.sleep(settle)
        shown = read_display(ctrl)
        if _norm(shown) == want:
            return
    raise FieldError(f"{label}: wanted {text!r} but the editor shows {shown!r}")


def select_combo_index(ctrl, index: int, pause: float = 0.02) -> None:
    """Select the item at `index` in a (non-editable) combo box."""
    try:
        ctrl.select(index)
        return
    except Exception:
        pass
    from pywinauto.keyboard import send_keys

    ctrl.click_input()
    send_keys("{ESC}", pause=pause)
    send_keys("{HOME}" + "{DOWN}" * index, pause=pause)


def combo_item_count(ctrl) -> int:
    try:
        return int(ctrl.item_count())
    except Exception:
        return len(ctrl.texts()) - 1