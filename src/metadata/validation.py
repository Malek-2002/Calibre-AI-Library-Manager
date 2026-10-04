"""Validate / normalise the LLM answer before it touches the metadata."""
from typing import Any

from .cleaning import AUTHOR_SEP, TAG_SEP, clean_list, clean_str, normalize_date
from .isbn import normalize_isbn


def clean_llm_record(raw: Any) -> dict:
    """Return a normalised record (with `confidence`), or {} if unusable."""
    if not isinstance(raw, dict):
        return {}
    try:
        rating = round(min(max(float(raw.get("rating") or 0), 0.0), 5.0), 2)
    except (TypeError, ValueError):
        rating = 0.0
    try:
        confidence = min(max(float(raw.get("confidence", 0.5)), 0.0), 1.0)
    except (TypeError, ValueError):
        confidence = 0.5

    series = clean_str(raw.get("series"))
    if series.lower() in {"standalone", "stand-alone", "no series"}:
        series = ""

    return {
        "title": clean_str(raw.get("title")),
        "authors": clean_list(raw.get("authors"), AUTHOR_SEP),
        "rating": rating,
        "tags": clean_list(raw.get("tags"), TAG_SEP)[:10],
        "series": series,
        "publisher": clean_str(raw.get("publisher")),
        "publish_date": normalize_date(raw.get("publish_date")),
        "comments": clean_str(raw.get("comments"))[:1200],
        # checksum guards against hallucinated ISBNs
        "isbn": normalize_isbn(clean_str(raw.get("isbn"))),
        "confidence": confidence,
    }


def clean_identity_record(raw: Any) -> dict:
    """Normalise the LLM's identification answer ({} if unusable)."""
    if not isinstance(raw, dict):
        return {}
    try:
        confidence = min(max(float(raw.get("confidence", 0.5)), 0.0), 1.0)
    except (TypeError, ValueError):
        confidence = 0.5
    return {
        "title": clean_str(raw.get("title")),
        "authors": clean_list(raw.get("authors"), AUTHOR_SEP),
        "isbn": normalize_isbn(clean_str(raw.get("isbn"))),
        "confidence": confidence,
    }
