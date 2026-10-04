"""OCR.space cloud engine (https://ocr.space/ocrapi).

.env:
    OCR_API_KEY=...            required
    OCR_SPACE_ENGINE=2         optional: 1 | 2 | 3 (default: 2 for English, 1 otherwise)
    OCR_SPACE_URL=...          optional: e.g. a PRO endpoint
    OCR_SPACE_MAX_BYTES=...    optional: upload limit (free plan = 1 MB per file)

Free plan limits: 1 MB per image, ~500 requests/day. Errors (limit hit, bad key,
timeout) raise OCRError, so core.py simply falls through to the next engine.
"""
import io
import os

import httpx
from PIL import Image

from ..errors import OCRError

DEFAULT_URL = "https://api.ocr.space/parse/image"
DEFAULT_MAX_BYTES = 1_000_000

# tesseract language code -> OCR.space code (only where they differ)
_LANG = {"fra": "fre", "deu": "ger", "chi_sim": "chs", "chi_tra": "cht", "ell": "gre", "nld": "dut"}


def _encode(img: Image.Image) -> bytes:
    """Grayscale JPEG under the upload limit: lower the quality first, then the size."""
    limit = int(os.getenv("OCR_SPACE_MAX_BYTES") or DEFAULT_MAX_BYTES)
    img = img.convert("L")
    for _ in range(8):
        for quality in (85, 70, 55):
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=quality)
            if buf.tell() <= limit:
                return buf.getvalue()
        img = img.resize((int(img.width * 0.8), int(img.height * 0.8)), Image.LANCZOS)
    raise OCRError("could not shrink the image under the OCR.space size limit")


def run(img: Image.Image, *, lang: str = "eng", ask_fn=None) -> str:
    key = os.getenv("OCR_API_KEY")
    if not key:
        raise OCRError("OCR_API_KEY is not set")

    first = (lang or "eng").split("+")[0]  # OCR.space accepts ONE language per request
    code = _LANG.get(first, first)
    engine = os.getenv("OCR_SPACE_ENGINE") or ("2" if code == "eng" else "1")

    try:
        resp = httpx.post(
            os.getenv("OCR_SPACE_URL") or DEFAULT_URL,
            data={
                "apikey": key,
                "language": code,
                "OCREngine": engine,
                "isOverlayRequired": "false",
                "detectOrientation": "true",
                "scale": "true",
            },
            files={"file": ("page.jpg", _encode(img), "image/jpeg")},
            timeout=60,
        )
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPError as e:
        raise OCRError(f"OCR.space request failed: {e}") from e
    except ValueError as e:
        raise OCRError("OCR.space returned invalid JSON") from e

    if payload.get("IsErroredOnProcessing") or payload.get("OCRExitCode") not in (1, 2):
        msg = payload.get("ErrorMessage") or payload.get("ErrorDetails") or "unknown error"
        if isinstance(msg, list):
            msg = "; ".join(map(str, msg))
        raise OCRError(f"OCR.space error: {msg}")

    return "\n".join((r.get("ParsedText") or "") for r in payload.get("ParsedResults") or [])
