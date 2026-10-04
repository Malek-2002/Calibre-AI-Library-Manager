"""EPUB implementation.

Embedded data : the OPF package document (Dublin Core + calibre / EPUB3 series info).
Front text    : an EPUB has no pages, so a "page" is one document of the reading order
                (spine). The first `pages` documents that have content are used:
                  - a document with text      -> its text
                  - an image-only document     -> OCR of its image (typical for covers / scans)
                  - blank documents and the navigation document are skipped.
The ISBN is also searched in the first few documents (copyright pages are often 3rd-5th).
"""
import io
import logging
import posixpath
import zipfile
from typing import Any
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
from PIL import Image

from ocr import OCRError, ocr_image

from ..cleaning import AUTHOR_SEP, clean_list, clean_str, normalize_date
from ..extractor import BookMetadataExtractor
from ..isbn import find_isbn
from ..models import BookMetadata

log = logging.getLogger(__name__)

MIN_DOC_CHARS = 20       # at least this many letters/digits => a full text document
MIN_SHORT_CHARS = 3      # below this a document is blank; between the two it is a title-page-like stub
MAX_SPINE_SCAN = 15      # never walk more than this many documents looking for content
ISBN_SCAN_DOCS = 10      # documents searched for a printed ISBN
DOC_TEXT_CAP = 3000      # characters kept per document (chapter 1 may be the whole book)
_RASTER = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff")


# --------------------------------------------------------------------------- #
# package (OPF) helpers
# --------------------------------------------------------------------------- #
def _local(tag: Any) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _attr(el: ET.Element, name: str) -> str:
    """Attribute by local name, whatever its namespace (opf:role, xlink:href, ...)."""
    for key, value in el.attrib.items():
        if _local(key) == name:
            return value
    return ""


def _open_opf(zf: zipfile.ZipFile) -> tuple[str, ET.Element]:
    opf_path = ""
    if "META-INF/container.xml" in zf.namelist():
        for el in ET.fromstring(zf.read("META-INF/container.xml")).iter():
            if _local(el.tag) == "rootfile" and el.get("full-path"):
                opf_path = el.get("full-path", "")
                break
    if not opf_path:
        opf_path = next((n for n in zf.namelist() if n.lower().endswith(".opf")), "")
    if not opf_path:
        raise ValueError("no OPF package document found in the EPUB")
    return opf_path, ET.fromstring(zf.read(opf_path))


def _spine(zf: zipfile.ZipFile, root: ET.Element, opf_path: str) -> list[str]:
    """Archive paths of the reading-order documents (navigation and non-linear ones removed)."""
    base, names = posixpath.dirname(opf_path), set(zf.namelist())
    manifest = {
        el.get("id"): (el.get("href", ""), el.get("properties", ""), el.get("media-type", ""))
        for el in root.iter() if _local(el.tag) == "item"
    }
    out = []
    for el in root.iter():
        if _local(el.tag) != "itemref" or el.get("linear") == "no":
            continue
        href, props, media = manifest.get(el.get("idref"), ("", "", ""))
        if not href or "nav" in props.split():
            continue
        if media and not media.startswith(("application/xhtml", "text/html")):
            continue
        path = posixpath.normpath(posixpath.join(base, unquote(href.split("#")[0])))
        if path in names:
            out.append(path)
    return out


def _position(value: Any) -> str:
    try:
        f = float(value)
        return str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        return clean_str(value)


def _read_opf_metadata(root: ET.Element) -> BookMetadata:
    meta = BookMetadata()
    md = next((el for el in root if _local(el.tag) == "metadata"), None)
    if md is None:
        return meta

    titles, creators, subjects, identifiers = [], [], [], []
    publisher = date = description = ""
    calibre: dict[str, str] = {}
    collections: dict[str, dict[str, str]] = {}   # EPUB3 belongs-to-collection
    refinements: list[tuple[str, str, str]] = []

    for el in md:
        name, text = _local(el.tag), clean_str("".join(el.itertext()))
        if name == "title":
            titles.append(text)
        elif name == "creator":
            if _attr(el, "role").lower() in ("", "aut"):   # skip translators, illustrators, editors
                creators.append(text)
        elif name == "publisher":
            publisher = publisher or text
        elif name == "date":
            date = date or text
        elif name == "description":
            description = description or text
        elif name == "subject":
            subjects.append(text)
        elif name == "identifier":
            identifiers.append(text)
        elif name == "meta":
            if el.get("name"):
                calibre[el.get("name", "")] = el.get("content", "")
            elif el.get("property") == "belongs-to-collection":
                collections[el.get("id", "")] = {"name": text}
            elif el.get("refines") and el.get("property") in ("collection-type", "group-position"):
                refinements.append((el.get("refines", "").lstrip("#"), el.get("property", ""), text))

    meta.fill("title", next((t for t in titles if t), ""), "embedded")
    authors = [a for c in creators for a in clean_list(c, AUTHOR_SEP)]
    meta.fill("authors", clean_list(authors), "embedded")
    meta.fill("publisher", publisher, "embedded")
    meta.fill("publish_date", normalize_date(date), "embedded")
    meta.fill("tags", clean_list(subjects)[:10], "embedded")
    if description:
        meta.fill("comments", clean_str(BeautifulSoup(description, "html.parser").get_text(" ")), "embedded")

    for ident in identifiers:
        isbn = find_isbn(ident if "isbn" in ident.lower() else f"ISBN {ident}")
        if isbn:
            meta.fill("isbn", isbn, "embedded")
            break

    series = clean_str(calibre.get("calibre:series"))
    position = _position(calibre.get("calibre:series_index")) if series and calibre.get("calibre:series_index") else ""
    if not series:
        for cid, prop, value in refinements:
            if cid in collections:
                collections[cid][prop] = value
        for info in collections.values():
            if info.get("collection-type", "").lower() == "series" and info.get("name"):
                series, position = info["name"], _position(info.get("group-position"))
                break
    if series:
        meta.fill("series", f"{series} #{position}" if position else series, "embedded")
    return meta


# --------------------------------------------------------------------------- #
# document helpers
# --------------------------------------------------------------------------- #
def _doc_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    lines = (line.strip() for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line)


def _first_image(soup: BeautifulSoup, doc_path: str, names: set[str]) -> str:
    """Archive path of the first raster image the document shows (<img> or svg <image>)."""
    for tag in soup.find_all(["img", "image"]):
        src = tag.get("src") or tag.get("xlink:href") or tag.get("href") or ""
        if not src or src.startswith("data:"):
            continue
        path = posixpath.normpath(posixpath.join(posixpath.dirname(doc_path), unquote(src.split("#")[0])))
        if path in names and path.lower().endswith(_RASTER):
            return path
    return ""


def _ocr_bytes(data: bytes) -> str:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return ocr_image(img)[0].strip()
    except (OCRError, OSError) as e:
        log.warning("EPUB image OCR failed: %s", e)
        return ""


class EpubMetadataExtractor(BookMetadataExtractor):
    # ---- 1. embedded metadata (OPF) -------------------------------------- #
    def read_embedded(self) -> BookMetadata:
        with zipfile.ZipFile(self.path) as zf:
            opf_path, root = _open_opf(zf)
            meta = _read_opf_metadata(root)
            if not meta.isbn:  # printed on a copyright page, not declared in the OPF
                for doc in _spine(zf, root, opf_path)[:ISBN_SCAN_DOCS]:
                    isbn = find_isbn(_doc_text(BeautifulSoup(zf.read(doc), "html.parser")))
                    if isbn:
                        meta.fill("isbn", isbn, "text")
                        break
        return meta

    # ---- 2. first documents: text, OCR for image-only ones --------------- #
    def read_front_text(self) -> tuple[str, str]:
        """Text of the first `pages` content documents -> (text, source) with source in text|ocr|mixed|none."""
        parts: list[str] = []
        used: set[str] = set()
        with zipfile.ZipFile(self.path) as zf:
            opf_path, root = _open_opf(zf)
            names, counted = set(zf.namelist()), 0
            for doc in _spine(zf, root, opf_path)[:MAX_SPINE_SCAN]:
                if counted >= self.pages:
                    break
                soup = BeautifulSoup(zf.read(doc), "html.parser")
                image = _first_image(soup, doc, names)   # before _doc_text mutates the soup
                text = _doc_text(soup)
                chars = sum(c.isalnum() for c in text)
                if chars >= MIN_DOC_CHARS:
                    parts.append(text[:DOC_TEXT_CAP])
                    used.add("text")
                    counted += 1
                elif image:  # cover / scanned page: the words are inside the picture
                    counted += 1
                    if chars >= MIN_SHORT_CHARS:  # e.g. an <h1>Cover</h1> next to the picture
                        parts.append(text)
                        used.add("text")
                    log.info("%s: %s has no real text -> OCR of %s", self.path.name, doc, image)
                    ocr_text = _ocr_bytes(zf.read(image))
                    if ocr_text:
                        parts.append(ocr_text)
                        used.add("ocr")
                elif chars >= MIN_SHORT_CHARS:  # title page: just "WOOL / Hugh Howey"
                    parts.append(text)
                    used.add("text")
                    counted += 1
                # blank documents (no text, no image) are skipped and not counted
        if not parts:
            return "", "none"
        return "\n\n".join(parts), (used.pop() if len(used) == 1 else "mixed")
