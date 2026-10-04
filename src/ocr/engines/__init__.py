"""OCR engine registry.

An engine is `run(img, *, lang, ask_fn) -> str`. To add one, create a module
here and register it below.
"""
from . import llm_vision, ocrspace, tesseract

ENGINES = {
    "ocrspace": ocrspace.run,
    "tesseract": tesseract.run,
    "llm": llm_vision.run,
}
