import logging
from pathlib import Path
from typing import Any, Callable, Sequence

from PIL import Image

from .config import DEFAULT_DPI, DEFAULT_ENGINES, DEFAULT_LANG
from .engines import ENGINES
from .errors import OCRError
from .models import OCRPage
from .preprocess import is_blank, is_useful, preprocess
from .render import render_pdf_pages

log = logging.getLogger(__name__)


def ocr_image(
    image: Path | str | Image.Image,
    *,
    lang: str = DEFAULT_LANG,
    engines: Sequence[str] = DEFAULT_ENGINES,
    ask_fn: Callable[..., Any] | None = None,
) -> tuple[str, str]:
    """OCR one image -> (text, engine_name).

    Falls through the engines until one returns useful text. A blank page
    returns ("", "none"); OCRError is raised only if every engine *failed*.
    """
    img = image if isinstance(image, Image.Image) else Image.open(image)
    if is_blank(img):  # checked before preprocess (autocontrast would amplify noise)
        return "", "none"
    img = preprocess(img)

    errors: list[str] = []
    best_text, best_engine = "", "none"
    for name in engines:
        try:
            if name not in ENGINES:
                raise OCRError(f"unknown OCR engine '{name}'")
            text = ENGINES[name](img, lang=lang, ask_fn=ask_fn).strip()
        except Exception as e:
            log.warning("OCR engine %s failed: %s", name, e)
            errors.append(f"{name}: {e}")
            continue

        if is_useful(text):
            return text, name
        if len(text) > len(best_text):
            best_text, best_engine = text, name

    if len(errors) == len(engines):
        raise OCRError("all OCR engines failed: " + "; ".join(errors))
    return best_text, best_engine


def ocr_pdf(
    path: Path | str,
    *,
    pages: int = 3,
    page_numbers: Sequence[int] | None = None,
    dpi: int = DEFAULT_DPI,
    lang: str = DEFAULT_LANG,
    engines: Sequence[str] = DEFAULT_ENGINES,
    ask_fn: Callable[..., Any] | None = None,
) -> list[OCRPage]:
    """OCR the first `pages` pages of a PDF, or exactly `page_numbers` (1-based) if given."""
    results: list[OCRPage] = []
    errors: list[str] = []
    for page_no, img in render_pdf_pages(path, pages=pages, dpi=dpi, page_numbers=page_numbers):
        try:
            text, engine = ocr_image(img, lang=lang, engines=engines, ask_fn=ask_fn)
            results.append(OCRPage(page_no, text, engine))
        except OCRError as e:
            log.warning("OCR failed on page %d: %s", page_no, e)
            errors.append(f"page {page_no}: {e}")
    if not results:
        raise OCRError("OCR failed on every page: " + "; ".join(errors))
    return results


def ocr_pdf_text(path: Path | str, **kwargs: Any) -> str:
    """OCR the first pages and join them into one string."""
    return "\n\n".join(p.text for p in ocr_pdf(path, **kwargs) if p.text)
