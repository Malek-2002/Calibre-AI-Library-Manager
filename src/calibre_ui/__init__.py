"""Calibre UI automation: add a book (or a new format of it) to a running Calibre, with metadata.

    from calibre_ui import add_to_calibre
    result = add_to_calibre("books/Wool.epub", metadata)     # metadata: dict / object / BookDetails
    print(result.outcome)                                     # added | format_added | skipped_same_format
"""
from calibre_ui.client import CalibreClient, add_to_calibre
from calibre_ui.config import UISettings, load_settings
from calibre_ui.errors import (BookDataError, CalibreUIError, ElementNotFound, FieldError, UITimeout)
from calibre_ui.models import AddResult, BookDetails, Outcome

__all__ = ["add_to_calibre", "CalibreClient", "BookDetails", "AddResult", "Outcome", "UISettings",
           "load_settings", "CalibreUIError", "UITimeout", "ElementNotFound", "FieldError", "BookDataError"]
