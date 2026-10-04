"""OCR package: turns image-only pages into text.

    from ocr import ocr_pdf_text, ocr_image, OCRError
"""
from .core import ocr_image, ocr_pdf, ocr_pdf_text
from .errors import OCRError
from .models import OCRPage

__all__ = ["ocr_image", "ocr_pdf", "ocr_pdf_text", "OCRError", "OCRPage"]
