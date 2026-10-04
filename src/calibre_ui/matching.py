"""Exact-match logic between a wanted book and rows of Calibre's table (pure, no UI)."""
import re
import unicodedata

from calibre_ui.config import UISettings
from calibre_ui.models import BookDetails, TableRow

_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"})


def norm(text: str | None) -> str:
    """Case-, whitespace- and quote-style-insensitive form used for exact comparisons."""
    s = unicodedata.normalize("NFKC", text or "").translate(_QUOTES)
    return re.sub(r"\s+", " ", s).strip().casefold()


def split_authors(cell: str) -> list[str]:
    """Calibre shows several authors as 'A & B'."""
    return [p.strip() for p in re.split(r"\s*[&;]\s*", cell or "") if p.strip()]


def same_authors(a: list[str], b: list[str]) -> bool:
    return sorted(norm(x) for x in a) == sorted(norm(x) for x in b)


def is_exact_match(row: TableRow, details: BookDetails, cfg: UISettings) -> bool:
    return (
        norm(row.values.get(cfg.t("col_title"))) == norm(details.title)
        and same_authors(split_authors(row.values.get(cfg.t("col_authors"), "")), details.authors)
    )


def find_exact(rows: list[TableRow], details: BookDetails, cfg: UISettings) -> TableRow | None:
    return next((r for r in rows if is_exact_match(r, details, cfg)), None)


def row_signature(row: TableRow) -> tuple:
    """Identity of a row based on everything visible in it (used to spot newly added rows)."""
    return tuple(sorted(row.values.items()))
