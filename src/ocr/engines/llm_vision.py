import tempfile
from pathlib import Path

from PIL import Image

from ..config import LLM_VISION_MODEL

PROMPT = (
    "Transcribe all the text visible in this image exactly as written, in "
    "reading order. Output only the transcription, with no commentary and no "
    "markdown. If there is no readable text, output nothing."
)


def run(img: Image.Image, *, lang: str = "eng", ask_fn=None) -> str:
    if ask_fn is None:
        from llm import ask as ask_fn  # lazy: OCR works without LLM configured
    img = img.copy()
    img.thumbnail((2000, 2000))  # keep the payload reasonable
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "page.png"
        img.save(p)
        kwargs = {"image": p}
        if LLM_VISION_MODEL:
            kwargs["model"] = LLM_VISION_MODEL
        return str(ask_fn(PROMPT, **kwargs))
