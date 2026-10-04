"""Calibre AI library manager - extract a book's metadata, then add it to Calibre.

Usage (run from E:\\Calibre):
    python src/main.py "books/Silo/Wool/Wool_-_Hugh_Howey.pdf"
    python src/main.py "books/Silo/Wool/Wool_-_Hugh_Howey.epub" --no-calibre   # extraction only
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from metadata import build_extractor  # noqa: E402

log = logging.getLogger("main")


# --------------------------------------------------------------------------- #
# Step 1: metadata extraction (file -> first pages / OCR -> LLM -> scrapers)
# --------------------------------------------------------------------------- #
def process_book(book_path: str | Path):
    """Run the complete extraction pipeline on a single book file and print a summary.

    Defaults applied:
      - LLM: enabled
      - Scrapers: enabled (Goodreads/Amazon)
      - Leading pages read: default (3 pages)
      - Show text: enabled

    Returns the extraction result object (use res.to_dict() for JSON, res.metadata for the fields).
    """
    path = Path(book_path)
    if not path.is_file():
        raise FileNotFoundError(f"Book file not found: {path}")

    extractor = build_extractor(
        path,
        model=None,      # Uses default model chain from llm.yaml
        use_llm=True,    # Always use LLM
        scrape=True,     # Always use web scrapers
        pages=3,         # Default leading page count
    )

    # Spy on front-page text extraction to report it
    captured: dict[str, str] = {}
    original_read_front = extractor.read_front_text

    def spy():
        text, source = original_read_front()
        captured["text"] = text
        return text, source

    extractor.read_front_text = spy

    t0 = time.perf_counter()
    res = extractor.extract()
    elapsed = time.perf_counter() - t0
    m = res.metadata

    print("=" * 72)
    print(f"File      : {path}")
    print(f"Text from : {res.text_source}   (first {extractor.pages} pages)")
    print(
        f"LLM       : {'used' if res.llm_used else 'not used'}"
        + (f", confidence {res.llm_confidence:.2f}" if res.llm_confidence is not None else "")
    )
    print(f"Scraped   : {', '.join(b['source'] for b in res.scraped) or 'nothing'}")
    print(f"Time      : {elapsed:.1f}s")
    print("-" * 72)

    rows = [
        ("title", m.title),
        ("authors", "; ".join(m.authors)),
        ("file_size", f"{m.file_size:,} bytes"),
        ("rating", m.rating or ""),
        ("tags", ", ".join(m.tags)),
        ("series", m.series),
        ("publisher", m.publisher),
        ("publish_date", m.publish_date),
        ("isbn", m.isbn),
        ("comments", m.comments),
    ]

    def _short(value, limit=160) -> str:
        s = str(value)
        return s if len(s) <= limit else s[: limit - 3] + "..."

    for name, value in rows:
        source = m.sources.get(name, "")
        print(f"{name:<13}{_short(value) if value else '(missing)':<64} {('[' + source + ']') if source else ''}")
    print("-" * 72)
    print(f"Missing   : {', '.join(res.missing) or 'none'}")
    for err in res.errors:
        print(f"Error     : {err}")

    print("-" * 72)
    print("FRONT TEXT (first 2000 chars):")
    print(captured.get("text", "")[:2000] or "(empty)")
    print("=" * 72)

    return res


# --------------------------------------------------------------------------- #
# Step 2: add the book to Calibre through its UI
# --------------------------------------------------------------------------- #
def add_book_to_calibre(path: Path, res) -> dict:
    """Search Calibre; add the book, add the missing format, or skip if that format is already there."""
    from calibre_ui import add_to_calibre  # imported here so --no-calibre works without pywinauto

    t0 = time.perf_counter()
    result = add_to_calibre(path, res.metadata)
    print("CALIBRE")
    print(f"Outcome   : {result.outcome.value}  ({result.format})")
    if result.fields_set:
        print(f"Written   : {', '.join(result.fields_set)}")
    for name, why in result.fields_failed.items():
        print(f"Not set   : {name} - {why}")
    if result.verified is not None:
        print(f"Verified  : {'yes, found again after saving' if result.verified else 'NO - not found after saving'}")
    print(f"Time      : {time.perf_counter() - t0:.1f}s")
    print("=" * 72)
    return result.to_dict()


# --------------------------------------------------------------------------- #
# Entry Point
# --------------------------------------------------------------------------- #
def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Extract a book's metadata and add it to Calibre.")
    parser.add_argument("book", help="Path to the book file (.pdf / .epub)")
    parser.add_argument("--no-calibre", action="store_true", help="Only extract metadata; do not touch Calibre")
    args = parser.parse_args()

    target_path = ROOT / args.book
    try:
        res = process_book(target_path)
        output = res.to_dict()
        output_file = ROOT / "output.json"

        if not args.no_calibre:
            try:
                output["calibre"] = add_book_to_calibre(target_path, res)
            except Exception as e:  # keep the extracted metadata even if the UI step fails
                log.exception("Adding to Calibre failed for %s: %s", target_path, e)
                output["calibre"] = {"error": str(e)}
                output_file.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
                print(f"Metadata saved to {output_file} (Calibre step failed)")
                return 1

        output_file.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"Metadata saved to {output_file}")
    except Exception as e:
        log.exception("Extraction failed for %s: %s", target_path, e)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())