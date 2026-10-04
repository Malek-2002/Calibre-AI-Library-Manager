"""Reads Calibre's book list (a UIA Table) into rows. Pure function over a snapshot."""
from datetime import datetime

from calibre_ui.models import TableRow
from calibre_ui.uia.query import find_all
from calibre_ui.uia.snapshot import Node


def parse_rows(nodes: list[Node]) -> list[TableRow]:
    """Map visible cells to (row, column) purely by geometry.

    Column headers share the topmost y; row headers ('1', '2', ...) sit below them. Hidden columns
    have empty rectangles and are ignored.
    """
    tables = find_all(nodes, type="Table")
    if not tables:
        return []
    area = tables[0].rect
    headers = find_all(nodes, type="Header", within=area)
    if not headers:
        return []
    top = min(h.rect.top for h in headers)
    columns = [h for h in headers if h.rect.top == top]
    row_headers = sorted((h for h in headers if h.rect.top > top), key=lambda h: h.rect.top)
    cells = find_all(nodes, type="DataItem", within=area)

    rows: list[TableRow] = []
    for rh in row_headers:
        values: dict[str, str] = {}
        first_cell: Node | None = None
        for cell in cells:
            if not rh.rect.top <= cell.rect.cy < rh.rect.bottom:
                continue
            col = next((c for c in columns if c.rect.left <= cell.rect.cx < c.rect.right), None)
            if col is not None:
                values[col.text.strip()] = cell.text
                if first_cell is None or cell.rect.left < first_cell.rect.left:
                    first_cell = cell
        if first_cell is not None:
            rows.append(TableRow(values=values, click_node=first_cell))

    # print("rows of the table: ", rows)
    return rows


def added_at(row: TableRow, date_column: str) -> datetime | None:
    """The row's 'Date' (date added) as a datetime, if the column is visible and parseable."""
    text = (row.values.get(date_column) or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None
