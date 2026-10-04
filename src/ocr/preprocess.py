from PIL import Image, ImageOps

from .config import MIN_USEFUL_CHARS


def preprocess(img: Image.Image) -> Image.Image:
    """Grayscale + autocontrast, and upscale small images (helps tesseract)."""
    img = ImageOps.autocontrast(img.convert("L"))
    longest = max(img.size)
    if longest < 1500:
        scale = 1500 / longest
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    return img


def is_useful(text: str) -> bool:
    return len("".join(text.split())) >= MIN_USEFUL_CHARS


def is_blank(img: Image.Image, max_dark_ratio: float = 2e-5) -> bool:
    """True when the page has (almost) no dark pixels: nothing to read, so skip OCR
    (and, above all, skip the paid LLM-vision fallback on empty pages)."""
    hist = img.convert("L").histogram()
    return sum(hist[:128]) / (img.width * img.height) < max_dark_ratio
