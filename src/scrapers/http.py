"""Polite HTTP fetching: rate limit per host, disk cache, block detection.

Deliberately NO captcha solving / proxy rotation / fingerprint spoofing: when a
site blocks us we stop talking to that host for the rest of the run and let the
pipeline fall back to the next source (and finally to the LLM).

.env:  SCRAPE_CACHE_DIR      default <project>/.cache/scrape
       SCRAPE_MIN_INTERVAL   seconds between requests to the same host (default 2.0)
       SCRAPE_CACHE_DAYS     cache lifetime (default 30)
"""
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_BLOCK_MARKERS = (
    "type the characters you see in this image",
    "enter the characters you see below",
    "api-services-support@amazon.com",
    "<title>robot check",
    "to discuss automated access to amazon data",
)


class ScrapeError(Exception):
    pass


class Blocked(ScrapeError):
    """The site refused us (captcha / 403 / 429 / 503)."""


class NotFound(ScrapeError):
    pass


_last_hit: dict[str, float] = {}
_blocked_hosts: set[str] = set()
_client: httpx.Client | None = None


def _cache_dir() -> Path:
    return Path(os.getenv("SCRAPE_CACHE_DIR") or ROOT / ".cache" / "scrape")


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(headers=HEADERS, follow_redirects=True, timeout=25)
    return _client


def fetch(url: str, params: dict | None = None) -> tuple[str, str]:
    """GET -> (html, final_url). Raises NotFound / Blocked / ScrapeError."""
    full = url + ("?" + urlencode(sorted(params.items())) if params else "")
    cache_file = _cache_dir() / (hashlib.sha1(full.encode()).hexdigest() + ".json")
    ttl = float(os.getenv("SCRAPE_CACHE_DAYS") or 30) * 86400
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < ttl:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        log.debug("cache hit %s", full)
        return data["html"], data["url"]

    host = urlparse(url).netloc
    if host in _blocked_hosts:
        raise Blocked(f"{host} blocked us earlier in this run; skipping")

    wait = float(os.getenv("SCRAPE_MIN_INTERVAL") or 2.0) - (time.monotonic() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)

    resp = None
    for attempt in range(3):
        _last_hit[host] = time.monotonic()
        try:
            resp = _get_client().get(url, params=params)
        except httpx.HTTPError as e:
            if attempt == 2:
                raise ScrapeError(f"request to {host} failed: {e}") from e
            time.sleep(2 * (attempt + 1))
            continue
        if resp.status_code == 404:
            raise NotFound(full)
        if resp.status_code in (403, 429, 503):
            _blocked_hosts.add(host)
            raise Blocked(f"HTTP {resp.status_code} from {host}")
        if resp.status_code >= 500 and attempt < 2:
            time.sleep(2 * (attempt + 1))
            continue
        break
    assert resp is not None
    if resp.status_code >= 400:
        raise ScrapeError(f"HTTP {resp.status_code} from {host}")

    html, final = resp.text, str(resp.url)
    if any(m in html.lower() for m in _BLOCK_MARKERS):
        _blocked_hosts.add(host)
        raise Blocked(f"{host} returned a bot-check page")

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"url": final, "html": html}), encoding="utf-8")
    return html, final
