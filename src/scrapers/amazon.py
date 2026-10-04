"""Amazon Books: product page by ISBN-10 (ASIN) or search -> product page.

Amazon blocks scrapers aggressively. A bot-check page raises Blocked (see http.py)
and the pipeline simply moves on. Used as a second source, after Goodreads.

.env:  AMAZON_DOMAIN=www.amazon.com
"""
import logging
import os
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from metadata.cleaning import clean_str, normalize_date
from metadata.isbn import normalize_isbn

from .http import NotFound, fetch
from .match import is_same_book, pick, search_queries
from .models import ScrapedBook

log = logging.getLogger(__name__)
_BIDI = dict.fromkeys(map(ord, "\u200e\u200f\u202a\u202b\u202c"), None)
_SERIES_PAREN = re.compile(r"\s*\((?:[^()]*\bbook\b[^()]*|[^()]*#\d+[^()]*)\)\s*$", re.I)


def _base() -> str:
    return "https://" + (os.getenv("AMAZON_DOMAIN") or "www.amazon.com")


def isbn13_to_10(isbn13: str) -> str:
    if len(isbn13) != 13 or not isbn13.startswith("978"):
        return ""
    core = isbn13[3:12]
    check = (11 - sum((10 - i) * int(c) for i, c in enumerate(core)) % 11) % 11
    return core + ("X" if check == 10 else str(check))


def lookup(*, title: str, authors: list[str], isbn: str) -> ScrapedBook | None:
    asin = isbn if len(isbn) == 10 else isbn13_to_10(isbn) if isbn else ""
    if asin:  # for books the ASIN is the ISBN-10
        try:
            html, url = fetch(f"{_base()}/dp/{asin}")
            book = parse_product_page(html, url)
            if book:
                return book
            log.warning("amazon: could not read %s (layout changed? raw HTML is in the cache folder)", url)
        except NotFound:
            log.info("amazon: ASIN %s not found, searching by title", asin)
    if not title:
        return None

    for query in search_queries(title, authors):
        html, _ = fetch(f"{_base()}/s", params={"k": query, "i": "stripbooks"})
        cands = parse_search(html)
        log.info("amazon: %d candidate(s) for %r", len(cands), query)
        hit = pick(cands, title, authors, "amazon")
        if not hit:
            continue
        html, url = fetch(urljoin(_base(), f"/dp/{hit['asin']}"))  # <- open the chosen product
        book = parse_product_page(html, url)
        if not book:
            log.warning("amazon: could not read %s (layout changed? raw HTML is in the cache folder)", url)
        elif is_same_book(title, authors, book.title, book.authors):
            log.info("amazon: matched %r (%s)", book.title, url)
            return book
        else:
            log.info("amazon: opened %r by %s - not the wanted book", book.title, ", ".join(book.authors))
    return None


def parse_search(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for div in soup.select('div[data-component-type="s-search-result"][data-asin]'):
        asin = div.get("data-asin", "").strip()
        h2 = div.select_one("h2")
        if not asin or not h2:
            continue
        text = clean_str(div.get_text(" "))
        m = re.search(r"\bby\s+(.+?)(?:\s+\||\s+\d{1,2}\s|$)", text)
        names = re.split(r",|\band\b|&", m.group(1)) if m else []
        out.append({"asin": asin, "title": clean_str(h2.get_text()),
                    "authors": [clean_str(n) for n in names if clean_str(n)]})
    return out


def _kv_pairs(soup: BeautifulSoup) -> dict[str, str]:
    """'Publisher : Century (June 1, 2011)' style rows from either detail layout."""
    pairs: dict[str, str] = {}
    for li in soup.select("#detailBullets_feature_div li, #detailBulletsWrapper_feature_div li"):
        text = clean_str(li.get_text(" ").translate(_BIDI))
        if ":" in text:
            k, v = text.split(":", 1)
            pairs.setdefault(k.strip().lower(), v.strip())
    for row in soup.select("#productDetailsTable li, #productDetails_detailBullets_sections1 tr"):
        text = clean_str(row.get_text(" ").translate(_BIDI))
        if ":" in text:
            k, v = text.split(":", 1)
            pairs.setdefault(k.strip().lower(), v.strip())
    for div in soup.select('[id^="rpi-attribute-book_details-"]'):
        val = div.select_one(".rpi-attribute-value")
        key = div["id"].replace("rpi-attribute-book_details-", "").replace("_", " ")
        if val:
            pairs.setdefault(key.lower(), clean_str(val.get_text(" ")))
    return pairs


def parse_product_page(html: str, url: str) -> ScrapedBook | None:
    soup = BeautifulSoup(html, "html.parser")
    book = ScrapedBook(source="amazon", url=url)
    try:
        t = soup.select_one("#productTitle")
        if t:
            book.fill("title", _SERIES_PAREN.sub("", clean_str(t.get_text())))
        book.fill("authors", [clean_str(a.get_text()) for a in soup.select("#bylineInfo span.author a.a-link-normal")
                              if clean_str(a.get_text())])

        rating = soup.select_one("#acrPopover")
        m = re.search(r"([\d.]+)\s+out of 5", (rating.get("title") if rating else "") or "")
        if m:
            book.fill("rating", round(float(m.group(1)), 2))

        series = soup.select_one("#seriesBulletWidget_feature_div a, #seriesBulletWidget_feature_div")
        m = re.search(r"Book\s+(\d+(?:\.\d+)?)\s+of\s+\d+:\s*(.+)", clean_str(series.get_text(" ")) if series else "")
        if m:
            book.fill("series", f"{clean_str(m.group(2))} #{m.group(1)}")

        desc = soup.select_one("#bookDescription_feature_div .a-expander-content, #bookDescription_feature_div")
        if desc:
            book.fill("comments", clean_str(desc.get_text(" "))[:4000])

        crumbs = [clean_str(a.get_text()) for a in soup.select("#wayfinding-breadcrumbs_feature_div a")]
        book.fill("tags", [c for c in crumbs if c and c.lower() != "books"][:8])

        kv = _kv_pairs(soup)
        pub = kv.get("publisher", "")
        m = re.match(r"(.*?)(?:;[^()]*)?\s*\(([^()]*\d{4}[^()]*)\)\s*$", pub)
        book.fill("publisher", clean_str(m.group(1) if m else pub))
        book.fill("publish_date", normalize_date((m.group(2) if m else "") or kv.get("publication date", "")))
        book.fill("isbn", normalize_isbn(kv.get("isbn-13", "") or kv.get("isbn13", ""))
                  or normalize_isbn(kv.get("isbn-10", "") or kv.get("isbn10", "")))
    except Exception as e:
        log.debug("amazon parse error: %s", e)
    return book if book.title else None
