"""Decide whether a scraped page is really the book we are looking for."""
import logging
import re
import unicodedata
from difflib import SequenceMatcher

log = logging.getLogger(__name__)
MIN_TITLE = 0.65


def _norm(title: str) -> str:
    s = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", s)   # "(Silo, #1)"
    s = s.split(":")[0]                       # drop subtitle
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def title_score(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if min(len(na), len(nb)) >= 4 and (f" {na} " in f" {nb} " or f" {nb} " in f" {na} "):  # whole words only
        return 0.9
    return SequenceMatcher(None, na, nb).ratio()


def _surname(name: str) -> str:
    name = name.split(",")[0] if "," in name else name
    tokens = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower())
    return tokens[-1] if tokens else ""


def authors_ok(want: list[str], got: list[str]) -> bool:
    """True if any surname overlaps. If either side is unknown we cannot disprove it."""
    w, g = {_surname(x) for x in want} - {""}, {_surname(x) for x in got} - {""}
    return not w or not g or bool(w & g)


def is_same_book(want_title: str, want_authors: list[str], got_title: str,
                 got_authors: list[str], min_title: float = MIN_TITLE) -> bool:
    return title_score(want_title, got_title) >= min_title and authors_ok(want_authors, got_authors)


def search_queries(title: str, authors: list[str]) -> list[str]:
    """Most specific query first; the title alone as a fallback (extra words can hurt the search)."""
    queries = [" ".join([title, authors[0]]).strip()] if authors else []
    queries.append(title)
    return list(dict.fromkeys(q for q in queries if q))


def pick(cands: list[dict], title: str, authors: list[str], source: str, min_title: float = MIN_TITLE) -> dict | None:
    """Choose the search result that is the wanted book: best title score among the
    candidates whose authors are compatible. Logs the top candidates so a miss is explainable."""
    scored = sorted(
        ((title_score(title, c.get("title", "")), authors_ok(authors, c.get("authors", [])), c) for c in cands),
        key=lambda x: (x[1], x[0]), reverse=True,
    )
    for ts, ok, c in scored[:5]:
        log.info("%s candidate: %r by %s | title score %.2f | author ok: %s",
                 source, c.get("title"), ", ".join(c.get("authors", [])) or "?", ts, ok)
    good = [(ts, c) for ts, ok, c in scored if ok and ts >= min_title]
    if not good:
        log.info("%s: none of %d candidate(s) matches %r by %s", source, len(cands), title, ", ".join(authors) or "?")
        return None
    return max(good, key=lambda x: x[0])[1]
