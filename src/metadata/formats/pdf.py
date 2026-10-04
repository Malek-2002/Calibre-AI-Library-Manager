"""PDF implementation: Info dict + XMP for embedded data, text layer or OCR for the first pages."""
import logging
import unicodedata
from typing import Any

from ocr import OCRError, ocr_pdf

from ..cleaning import AUTHOR_SEP, TAG_SEP, clean_list, clean_str
from ..extractor import BookMetadataExtractor
from ..isbn import find_isbn
from ..models import BookMetadata

log = logging.getLogger(__name__)

MIN_PAGE_CHARS = 20      # fewer letters/digits on a page => treat that page as an image
MIN_SANE_RATIO = 0.85    # share of "normal" characters below which the text is garbled


def _flat(v: Any) -> list[str]:
    """XMP values come back as str / list / {lang: value} depending on the field."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [s for x in v.values() for s in _flat(x)]
    if isinstance(v, (list, tuple, set)):
        return [s for x in v for s in _flat(x)]
    return [str(v)]


def _first(v: Any) -> str:
    for s in _flat(v):
        if clean_str(s):
            return clean_str(s)
    return ""


class PdfMetadataExtractor(BookMetadataExtractor):
    # ---- 1. embedded metadata ------------------------------------------- #
    def read_embedded(self) -> BookMetadata:
        from pypdf import PdfReader

        reader = PdfReader(str(self.path))
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception:
                unlocked = 0
            if not unlocked:
                raise ValueError("PDF is password-protected")

        meta = BookMetadata()
        info = reader.metadata
        if info is not None:
            meta.fill("title", clean_str(info.title), "embedded")
            meta.fill("authors", clean_list(info.author, AUTHOR_SEP), "embedded")
            meta.fill("tags", clean_list(info.get("/Keywords"), TAG_SEP)[:10], "embedded")
            subject = clean_str(info.subject)
            if len(subject) >= 40:  # short subjects are usually junk, not a description
                meta.fill("comments", subject, "embedded")

        self._fill_from_xmp(reader, meta)
        # /CreationDate is when the PDF was made, not when the book was published:
        # deliberately not used for publish_date.
        return meta

    @staticmethod
    def _fill_from_xmp(reader: Any, meta: BookMetadata) -> None:
        try:
            xmp = reader.xmp_metadata
        except Exception:
            return
        if xmp is None:
            return

        def get(attr: str) -> Any:
            try:
                return getattr(xmp, attr)
            except Exception:
                return None

        meta.fill("title", _first(get("dc_title")), "embedded")
        meta.fill("authors", clean_list(_flat(get("dc_creator"))), "embedded")
        meta.fill("publisher", _first(get("dc_publisher")), "embedded")
        meta.fill("tags", clean_list(_flat(get("dc_subject")))[:10], "embedded")
        meta.fill("comments", _first(get("dc_description")), "embedded")
        for ident in _flat(get("dc_identifier")):
            isbn = find_isbn(ident if "isbn" in ident.lower() else f"ISBN {ident}")
            if isbn:
                meta.fill("isbn", isbn, "embedded")
                break

    # ---- 2. first pages: text layer per page, OCR only for the bad pages -- #
    def read_front_text(self) -> tuple[str, str]:
        """Text of the first pages -> (text, source) with source in text|ocr|mixed|none.

        Every page is judged on its own: a page with a usable text layer keeps it,
        an image-only / garbled page is OCR'd (e.g. cover + page 2 scanned, page 3 real text).
        """
        texts = self._page_texts()
        if not texts:  # text layer unreadable altogether -> try OCR on all leading pages
            texts = [""] * self.pages
        bad = [i for i, t in enumerate(texts, start=1) if not self._usable(t)]

        ocr_by_page: dict[int, str] = {}
        if bad:
            log.info("%s: no usable text on page(s) %s -> OCR for those pages",
                     self.path.name, bad)
            try:
                for page in ocr_pdf(self.path, page_numbers=bad):
                    ocr_by_page[page.page] = page.text.strip()
            except OCRError as e:
                log.warning("OCR failed for %s: %s", self.path, e)

        parts: list[str] = []
        used: set[str] = set()
        for i, raw in enumerate(texts, start=1):
            if i in bad:
                if ocr_by_page.get(i):
                    parts.append(ocr_by_page[i])
                    used.add("ocr")
                elif raw.strip():  # OCR found nothing: keep whatever the text layer had
                    parts.append(raw.strip())
                    used.add("text")
            else:
                parts.append(raw.strip())
                used.add("text")

        text = "\n\n".join(parts)
        if not text.strip():
            return "", "none"
        return text, (used.pop() if len(used) == 1 else "mixed")

    def _page_texts(self) -> list[str]:
        """Raw text layer of each leading page, or [] if it cannot be read."""
        try:
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(str(self.path))
            try:
                texts = []
                for i in range(min(self.pages, len(pdf))):
                    page = pdf[i]
                    textpage = page.get_textpage()
                    texts.append(textpage.get_text_range())
                    textpage.close()
                    page.close()
                return texts
            finally:
                pdf.close()
        except Exception as e:
            log.debug("pdfium text extraction failed (%s), trying pypdf", e)

        try:
            from pypdf import PdfReader

            reader = PdfReader(str(self.path))
            return [
                (reader.pages[i].extract_text() or "")
                for i in range(min(self.pages, len(reader.pages)))
            ]
        except Exception as e:
            log.debug("pypdf text extraction failed: %s", e)
            return []

    @staticmethod
    def _usable(text: str) -> bool:
        """False for an image-only page (no text) or a garbled/corrupt text layer."""
        if sum(c.isalnum() for c in text) < MIN_PAGE_CHARS:
            return False
        sane = sum(1 for c in text if c.isspace() or unicodedata.category(c)[0] in "LNPZ")
        return sane / len(text) >= MIN_SANE_RATIO and text.count("\ufffd") / len(text) < 0.05
