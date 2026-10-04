from dataclasses import dataclass


@dataclass
class OCRPage:
    page: int      # 1-based page number
    text: str
    engine: str    # engine that produced the text ("tesseract" / "llm" / "none")
