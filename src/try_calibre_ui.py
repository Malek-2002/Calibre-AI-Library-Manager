"""Add a book to a running Calibre through its UI.

Examples (run from the project root, Calibre open):
  python src/try_calibre_ui.py "books/Wool.epub" --metadata output.json
  python src/try_calibre_ui.py "books/Wool.pdf" --title Wool --author "Hugh Howey"
  python src/try_calibre_ui.py "books/Wool.epub" --metadata output.json --dry-run
"""
import argparse
import json
import logging
import sys
from pathlib import Path

from calibre_ui import BookDetails, CalibreUIError, add_to_calibre


def load_details(args) -> BookDetails:
    data: dict = {}
    if args.metadata:
        data = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
        data = data.get("metadata", data)          # accept {"metadata": {...}} or a flat dict
    if args.title:
        data["title"] = args.title
    if args.author:
        data["authors"] = args.author
    return BookDetails.from_any(data)


def main() -> int:
    p = argparse.ArgumentParser(description="Add a book to Calibre via UI automation.")
    p.add_argument("book", help="Path to the book file (.pdf, .epub, ...)")
    p.add_argument("--metadata", help="JSON file with the extracted metadata (e.g. output.json)")
    p.add_argument("--title")
    p.add_argument("--author", action="append", help="Repeat for several authors")
    p.add_argument("--dry-run", action="store_true", help="Only show what would be searched/written")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    try:
        details = load_details(args)
        if args.dry_run:
            from calibre_ui.search_query import build_query
            print("search :", build_query(details))
            print(json.dumps(details.__dict__, indent=2, ensure_ascii=False, default=str))
            return 0
        print(json.dumps(add_to_calibre(args.book, details).to_dict(), indent=2))
        return 0
    except CalibreUIError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
