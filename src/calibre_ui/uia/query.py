"""Pure lookups over a snapshot (find by type/text/area, resolve a label to its input field)."""
import re

from calibre_ui.errors import ElementNotFound
from calibre_ui.uia.snapshot import Node, Rect

INPUT_TYPES = ("Edit", "ComboBox", "Spinner")


def find_all(nodes: list[Node], *, type: str | None = None, text: str | None = None,
             text_re: str | None = None, within: Rect | None = None, visible: bool = True) -> list[Node]:
    rx = re.compile(text_re) if text_re else None
    out = []
    for n in nodes:
        if type and n.type != type:
            continue
        if text is not None and n.text.strip() != text:
            continue
        if rx and not rx.search(n.text):
            continue
        if within is not None and not within.contains(n.rect):
            continue
        if visible and not n.rect.visible:
            continue
        out.append(n)
    return out


def find_one(nodes: list[Node], what: str, **kw) -> Node:
    hits = find_all(nodes, **kw)
    if not hits:
        raise ElementNotFound(f"Could not find {what} in the Calibre window")
    return hits[0]


def largest(nodes: list[Node]) -> Node:
    return max(nodes, key=lambda n: n.rect.area)


def field_for_label(nodes: list[Node], label: str, types=INPUT_TYPES) -> Node:
    """The input control sitting to the right of the Static text `label`, on the same row.

    Editable combo boxes resolve to their inner Edit; a combo without one (e.g. Rating) stays a ComboBox.
    """
    labels = find_all(nodes, type="Text", text=label)
    if not labels:
        raise ElementNotFound(f"Label {label!r} not found")
    lab = labels[0]

    def same_row(c: Node) -> bool:
        return abs(c.rect.cy - lab.rect.cy) <= max(lab.rect.height, c.rect.height) / 2

    cands = [c for c in find_all(nodes, type=None) if c.type in types
             and c.rect.left >= lab.rect.right - 2 and same_row(c)]
    if not cands:
        raise ElementNotFound(f"No input field found next to label {label!r}")
    cand = min(cands, key=lambda c: c.rect.left)
    if cand.type == "ComboBox":
        inner = find_all(nodes, type="Edit", within=cand.rect)
        if inner:
            return inner[0]
    return cand
