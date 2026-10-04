"""Book format helpers (Calibre names formats by upper-case extension)."""
import re
from pathlib import Path


def format_of(path: Path | str) -> str:
    """'/x/Wool.epub' -> 'EPUB'."""
    return Path(path).suffix.lstrip(".").upper()


def parse_format_item(text: str) -> str | None:
    """'EPUB (0.78 MB)' -> 'EPUB'."""
    m = re.match(r"^\s*([A-Za-z0-9_.]+)\s*\(", text or "")
    return m.group(1).upper() if m else None


def has_format(existing: list[str], fmt: str) -> bool:
    return fmt.upper() in {f.upper() for f in existing}
