"""OCR defaults. Engines are tried in this order until one returns useful text."""
import os
from pathlib import Path

try:  # so OCR_LLM_MODEL / OCR_API_KEY / TESSERACT_CMD work even if ocr is imported first
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

# cloud OCR first (OCR_API_KEY), then local tesseract, then the LLM vision call as last resort
DEFAULT_ENGINES: tuple[str, ...] = ("ocrspace", "tesseract", "llm")
DEFAULT_LANG = "eng"      # tesseract language(s), e.g. "eng+ara"
DEFAULT_DPI = 200         # PDF render resolution
MIN_USEFUL_CHARS = 25     # fewer non-space chars than this = "engine found nothing"

# llm.yaml profile used by the "llm" (vision) engine. It must accept images, e.g. "gemini".
# Set OCR_LLM_MODEL in .env. Unset = llm.ask default + fallback chain (a text-only default
# model can fail on every image before falling through).
LLM_VISION_MODEL: str | None = os.getenv("OCR_LLM_MODEL") or None
