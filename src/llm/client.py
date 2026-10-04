"""Public entry point: `ask(prompt)`."""
import json
import logging
from functools import lru_cache
from pathlib import Path

from .config import LLMConfigError, LLMSettings, load_settings
from .providers import PROVIDER_CLASSES, Provider

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _settings() -> LLMSettings:
    return load_settings()


@lru_cache(maxsize=None)
def _provider(name: str) -> Provider:
    cfg = _settings().models[name]
    return PROVIDER_CLASSES[cfg.provider](cfg)


def list_models() -> list[str]:
    return list(_settings().models)


def _strip_fences(text: str) -> str:
    return text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def ask(
    prompt: str,
    *,
    model: str | None = None,
    image: Path | str | None = None,
    schema: dict | None = None,
    parse_json: bool = False,
):
    """Send a prompt to an LLM and return the text reply.

    model:      profile name from llm.yaml (gemini / groq / openai). If omitted,
                tries `default`, then each entry in `fallback` until one succeeds.
                If given, only that profile is used (no fallback).
    image:      optional image path (png/jpg/webp) sent with the prompt.
    schema:     optional JSON schema; native on Gemini, JSON mode + prompt elsewhere.
    parse_json: return a parsed dict/list instead of a string.
    """
    settings = _settings()
    if model:
        if model not in settings.models:
            raise LLMError(f"Unknown model '{model}'. Available: {list_models()}")
        chain = [model]
    else:
        chain = [settings.default] + [m for m in settings.fallback if m != settings.default]

    img = Path(image) if image else None
    last_error: Exception | None = None

    for name in chain:
        try:
            log.info("LLM: trying %s", name)
            text = _provider(name).complete(prompt, img, schema).strip()
            if parse_json or schema:
                text = _strip_fences(text)
            return json.loads(text) if parse_json else text
        except LLMConfigError as e:
            log.warning("LLM %s skipped (config): %s", name, e)
            last_error = e
        except Exception as e:  # provider/network/JSON errors -> next in chain
            log.warning("LLM %s failed: %s", name, e)
            last_error = e

    raise LLMError(f"All models failed ({chain}). Last error: {last_error}") from last_error