import os
import shutil

from PIL import Image

from ..errors import OCRError
from ..preprocess import is_useful


def run(img: Image.Image, *, lang: str = "eng", ask_fn=None) -> str:
    # On Windows tesseract is often not on PATH: set TESSERACT_CMD in .env
    # e.g. TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
    cmd = os.getenv("TESSERACT_CMD") or os.getenv("TESSERACT") or shutil.which("tesseract")
    if not cmd or not (os.path.isfile(cmd) or shutil.which(cmd)):
        raise OCRError("tesseract not found (install it or set TESSERACT_CMD)")
    try:
        import pytesseract
    except ImportError as e:
        raise OCRError("pytesseract is not installed (pip install pytesseract)") from e

    pytesseract.pytesseract.tesseract_cmd = cmd
    text = pytesseract.image_to_string(img, lang=lang, config="--psm 3")
    if is_useful(text):
        return text
    # Covers / title pages are sparse layouts: retry in sparse-text mode.
    return pytesseract.image_to_string(img, lang=lang, config="--psm 11")
