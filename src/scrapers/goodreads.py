"""Goodreads: look a book up by ISBN (or title + author), CHOOSE the right search result,
open its page and parse it.

Search strategies, in order (each tolerant of layout changes):
  1. /book/auto_complete?format=json  - the JSON behind the site's search box
  2. /search?q=...                    - the HTML results page (any link to /book/show/<id>)
The book page itself is a Next.js app: its state lives in <script id="__NEXT_DATA__">
(plus JSON-LD), which is read first; HTML selectors are only a fallback.
"""
import json
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from metadata.cleaning import clean_str, normalize_date
from metadata.isbn import normalize_isbn

from .http import NotFound, ScrapeError, fetch
from .match import is_same_book, pick, search_queries
from .models import ScrapedBook

log = logging.getLogger(__name__)
BASE = "https://www.goodreads.com"


# --------------------------------------------------------------------------- #
# lookup
# --------------------------------------------------------------------------- #
def lookup(*, title: str, authors: list[str], isbn: str) -> ScrapedBook | None:
    if isbn:  # exact edition: /book/isbn/<isbn> redirects to the book page
        try:
            html, url = fetch(f"{BASE}/book/isbn/{isbn}")
            if "/book/show/" in url:
                book = parse_book_page(html, url)
                if book:
                    return book
                log.warning("goodreads: could not read %s (layout changed? raw HTML is in the cache folder)", url)
        except NotFound:
            log.info("goodreads: ISBN %s not found, searching by title", isbn)
    if not title:
        return None

    for query in search_queries(title, authors):
        cands, direct = _candidates(query)
        hit: dict = {}
        if direct:  # the search redirected straight to one book
            page_html, page_url = direct
        else:
            log.info("goodreads: %d candidate(s) for %r", len(cands), query)
            hit = pick(cands, title, authors, "goodreads") or {}
            if not hit:
                continue
            page_html, page_url = fetch(urljoin(BASE, hit["href"]))  # <- open the chosen book

        book = parse_book_page(page_html, page_url)
        if not book:
            log.warning("goodreads: could not read %s (layout changed? raw HTML is in the cache folder)", page_url)
            continue
        if not is_same_book(title, authors, book.title, book.authors):
            log.info("goodreads: opened %r by %s - not the wanted book", book.title, ", ".join(book.authors))
            continue
        if hit.get("rating"):
            try:
                book.fill("rating", round(float(hit["rating"]), 2))
            except (TypeError, ValueError):
                pass
        log.info("goodreads: matched %r (%s)", book.title, page_url)
        return book
    return None


def _candidates(query: str) -> tuple[list[dict], tuple[str, str] | None]:
    """-> (candidates, direct_page). direct_page=(html, url) if the search landed on a book."""
    try:
        text, _ = fetch(f"{BASE}/book/auto_complete", params={"format": "json", "q": query})
        cands = parse_autocomplete(text)
        if cands:
            return cands, None
    except ScrapeError as e:
        log.info("goodreads autocomplete unavailable (%s); using the search page", e)
    html, url = fetch(f"{BASE}/search", params={"q": query})
    if "/book/show/" in url:
        return [], (html, url)
    return parse_search(html), None


def parse_autocomplete(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    out = []
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict):
            continue
        href = d.get("bookUrl") or (f"/book/show/{d['bookId']}" if d.get("bookId") else "")
        name = clean_str((d.get("author") or {}).get("name"))
        if href:
            out.append({"href": href, "title": clean_str(d.get("bookTitleBare") or d.get("title")),
                        "authors": [name] if name else [], "rating": d.get("avgRating")})
    return out


def parse_search(html: str) -> list[dict]:
    """Any link to /book/show/<id> with text is a result; authors = author links in the same row/card."""
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"/book/show/\d+")):
        href = a["href"].split("?")[0]
        text = clean_str(a.get_text())
        if href in seen or not text:  # skip cover-image links (no text) and duplicates
            continue
        seen.add(href)
        box = a.find_parent(["tr", "article", "li"]) or a.parent
        names = [clean_str(x.get_text()) for x in (box.select('a[href*="/author/show/"]') if box else [])]
        out.append({"href": href, "title": text, "authors": list(dict.fromkeys(n for n in names if n))})
    return out


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
def _text(html_fragment: str) -> str:
    return clean_str(BeautifulSoup(html_fragment or "", "html.parser").get_text(" "))


def parse_book_page(html: str, url: str) -> ScrapedBook | None:
    soup = BeautifulSoup(html, "html.parser")
    book = ScrapedBook(source="goodreads", url=url)
    for step in (_from_next_data, _from_json_ld, _from_html):
        try:
            step(soup, book)
        except Exception as e:  # one broken parser must not lose the others' data
            log.debug("goodreads %s failed: %s", step.__name__, e)
    return book if book.title else None


def _from_next_data(soup: BeautifulSoup, book: ScrapedBook) -> None:
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag:
        return
    state = json.loads(tag.get_text())["props"]["pageProps"]["apolloState"]

    def ref(v):
        return state.get(v["__ref"]) if isinstance(v, dict) and "__ref" in v else v

    root = state.get("ROOT_QUERY", {})
    node = next((ref(v) for k, v in root.items() if k.startswith("getBookByLegacyId")), None)
    if not node:
        node = next((v for k, v in state.items()
                     if k.startswith("Book:") and isinstance(v, dict) and v.get("details")), None)
    if not isinstance(node, dict):
        return

    book.fill("title", clean_str(node.get("title")))
    desc = next((v for k, v in node.items() if k.startswith("description") and isinstance(v, str)), "")
    book.fill("comments", _text(desc)[:4000])

    names = []
    primary = ref((node.get("primaryContributorEdge") or {}).get("node")) or {}
    names.append(primary.get("name"))
    for edge in node.get("secondaryContributorEdges") or []:
        if (edge.get("role") or "").lower() == "author":
            names.append((ref(edge.get("node")) or {}).get("name"))
    book.fill("authors", [clean_str(n) for n in names if clean_str(n)])

    series = ""
    for item in node.get("bookSeries") or []:
        name = clean_str((ref(item.get("series")) or {}).get("title"))
        if name:
            pos = clean_str(item.get("userPosition"))
            series = f"{name} #{pos}" if pos else name
            break
    book.fill("series", series)

    genres = [clean_str((ref(i.get("genre")) or {}).get("name")) for i in node.get("bookGenres") or []]
    book.fill("tags", [g for g in genres if g][:8])

    d = node.get("details") or {}
    book.fill("publisher", clean_str(d.get("publisher")))
    book.fill("publish_date", normalize_date(d.get("publicationTime")))
    book.fill("isbn", normalize_isbn(d.get("isbn13") or "") or normalize_isbn(d.get("isbn") or ""))

    stats = (ref(node.get("work")) or {}).get("stats") or {}
    try:
        book.fill("rating", round(float(stats.get("averageRating") or 0), 2))
        book.fill("rating_count", int(stats.get("ratingsCount") or 0))
    except (TypeError, ValueError):
        pass


def _from_json_ld(soup: BeautifulSoup, book: ScrapedBook) -> None:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.get_text())
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict) or item.get("@type") != "Book":
                continue
            book.fill("title", clean_str(item.get("name")))
            auth = item.get("author")
            auth = auth if isinstance(auth, list) else [auth] if auth else []
            book.fill("authors", [clean_str(a.get("name") if isinstance(a, dict) else a) for a in auth if a])
            book.fill("isbn", normalize_isbn(str(item.get("isbn") or "")))
            rating = item.get("aggregateRating") or {}
            try:
                book.fill("rating", round(float(rating.get("ratingValue") or 0), 2))
                book.fill("rating_count", int(rating.get("ratingCount") or 0))
            except (TypeError, ValueError):
                pass
            return


def _from_html(soup: BeautifulSoup, book: ScrapedBook) -> None:
    h1 = soup.select_one('h1[data-testid="bookTitle"], h1#bookTitle')
    if h1:
        book.fill("title", clean_str(h1.get_text()))
    genres = []
    for a in soup.select('[data-testid="genresList"] a, .BookPageMetadataSection__genreButton a, a.bookPageGenreLink'):
        g = clean_str(a.get_text())
        if g and g not in genres:
            genres.append(g)
    book.fill("tags", genres[:8])
    desc = soup.select_one('[data-testid="description"], #description')
    if desc:
        book.fill("comments", clean_str(desc.get_text(" "))[:4000])
    pub = soup.select_one('[data-testid="publicationInfo"]')
    if pub:
        book.fill("publish_date", normalize_date(pub.get_text(" ")))
    rating = soup.select_one(".RatingStatistics__rating")
    if rating:
        try:
            book.fill("rating", round(float(rating.get_text().strip()), 2))
        except ValueError:
            pass
    if not book.series and soup.title:  # "<title>Wool (Silo, #1) by Hugh Howey"
        m = re.search(r"\(([^()#]+?),?\s*#(\d+(?:\.\d+)?)\)", soup.title.get_text())
        if m:
            book.fill("series", f"{clean_str(m.group(1))} #{m.group(2)}")
