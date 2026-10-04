"""Builds Calibre search expressions (pure)."""
from calibre_ui.models import BookDetails


def quote(value: str) -> str:
    """Quote a value for Calibre's search language."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_query(details: BookDetails, mode: str = "loose") -> str:
    """exact: title:"=Wool" and authors:"=Hugh Howey"   loose: title:"Wool" and authors:"Hugh Howey" """
    prefix = "=" if mode == "exact" else ""
    parts = [f"title:{quote(prefix + details.title)}"]
    parts += [f"authors:{quote(prefix + a)}" for a in details.authors]
    return " and ".join(parts)
