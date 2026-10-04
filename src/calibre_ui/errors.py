class CalibreUIError(RuntimeError):
    """Base class for every error raised by this package."""


class UITimeout(CalibreUIError):
    pass


class ElementNotFound(CalibreUIError):
    pass


class FieldError(CalibreUIError):
    """A value could not be written to (or verified in) a Calibre field."""


class BookDataError(CalibreUIError, ValueError):
    """The book path or the metadata handed to us is unusable."""
