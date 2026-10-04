"""A snapshot of a window's controls as plain data (type, text, rectangle).

One UIA walk, then every lookup is pure geometry on the snapshot: fast, and testable without Windows.
"""
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def cx(self) -> float:
        return (self.left + self.right) / 2

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    @property
    def visible(self) -> bool:
        return self.width > 0 and self.height > 0

    def contains(self, other: "Rect", tol: int = 2) -> bool:
        return (other.left >= self.left - tol and other.right <= self.right + tol
                and other.top >= self.top - tol and other.bottom <= self.bottom + tol)


@dataclass
class Node:
    ctrl: Any          # the live pywinauto wrapper
    type: str          # UIA control type: Button, Edit, Text, ComboBox, Spinner, ListItem, ...
    text: str
    rect: Rect


def snapshot(container) -> list[Node]:
    """Read every descendant of `container` once."""
    nodes: list[Node] = []
    for ctrl in container.descendants():
        try:
            r = ctrl.rectangle()
            nodes.append(Node(ctrl, ctrl.element_info.control_type, ctrl.window_text() or "",
                              Rect(r.left, r.top, r.right, r.bottom)))
        except Exception:
            continue  # element vanished while walking the tree
    return nodes
