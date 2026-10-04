"""PDF page rendering (pypdfium2 - no poppler needed)."""
import logging
from pathlib import Path
from typing import Sequence

from PIL import Image

from .config import DEFAULT_DPI
from .errors import OCRError

log = logging.getLogger(__name__)


def render_pdf_pages(
    path: Path | str,
    pages: int = 3,
    dpi: int = DEFAULT_DPI,
    page_numbers: Sequence[int] | None = None,
) -> list[tuple[int, Image.Image]]:
    """Render pages -> [(page_no, PIL image), ...] (page_no is 1-based).

    By default the first `pages` pages; pass `page_numbers` (1-based) to render
    exactly those pages instead. Numbers beyond the document length are skipped.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError as e:
        raise OCRError("pypdfium2 is not installed (pip install pypdfium2)") from e

    try:
        pdf = pdfium.PdfDocument(str(path))
    except Exception as e:  # corrupt / encrypted / not a PDF
        raise OCRError(f"cannot open PDF for rendering: {e}") from e

    rendered: list[tuple[int, Image.Image]] = []
    try:
        wanted = page_numbers if page_numbers is not None else range(1, pages + 1)
        for n in wanted:
            if n < 1 or n > len(pdf):
                continue
            try:
                page = pdf[n - 1]
                rendered.append((n, page.render(scale=dpi / 72).to_pil()))
                page.close()
            except Exception as e:
                log.warning("OCR: could not render page %d of %s: %s", n, path, e)
    finally:
        pdf.close()

    if not rendered:
        raise OCRError("no page could be rendered")
    return rendered
