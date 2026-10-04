"""One small adapter per provider. Each turns (prompt, image, schema) into text."""
import base64
import json
from abc import ABC, abstractmethod
from pathlib import Path

from .config import LLMConfigError, ModelConfig

_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _media_type(path: Path) -> str:
    return _MEDIA_TYPES.get(path.suffix.lower(), "image/png")


def _with_schema(prompt: str, schema: dict | None) -> str:
    """For providers without native schema support, put the schema in the prompt."""
    if not schema:
        return prompt
    return (
        f"{prompt}\n\nRespond with ONLY valid JSON (no markdown fences) matching this schema:\n"
        f"{json.dumps(schema)}"
    )


class Provider(ABC):
    def __init__(self, cfg: ModelConfig):
        if not cfg.api_key:
            raise LLMConfigError(f"No API key for model '{cfg.name}' (env var {cfg.api_key_env} is empty)")
        self.cfg = cfg

    @abstractmethod
    def complete(self, prompt: str, image: Path | None, schema: dict | None) -> str: ...


class GeminiProvider(Provider):
    def __init__(self, cfg):
        super().__init__(cfg)
        from google import genai
        self.client = genai.Client(api_key=cfg.api_key)

    def complete(self, prompt, image, schema):
        from google.genai import types

        contents: list = []
        if image:
            contents.append(types.Part.from_bytes(data=image.read_bytes(), mime_type=_media_type(image)))
        contents.append(prompt)

        config_kwargs: dict = {}
        if self.cfg.temperature is not None:
            config_kwargs["temperature"] = self.cfg.temperature
        if schema:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = schema  # native schema support

        resp = self.client.models.generate_content(
            model=self.cfg.model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        return resp.text or ""


class OpenAICompatibleProvider(Provider):
    """Shared by OpenAI and Groq (Groq exposes an OpenAI-compatible API)."""

    default_base_url: str | None = None

    def __init__(self, cfg):
        super().__init__(cfg)
        from openai import OpenAI
        self.client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url or self.default_base_url)

    def complete(self, prompt, image, schema):
        content: list[dict] = []
        if image:
            b64 = base64.b64encode(image.read_bytes()).decode()
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:{_media_type(image)};base64,{b64}"}})
        content.append({"type": "text", "text": _with_schema(prompt, schema)})

        kwargs: dict = {
            "model": self.cfg.model,
            "max_completion_tokens": self.cfg.max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        # Only send temperature if configured: some newer/reasoning models reject it.
        if self.cfg.temperature is not None:
            kwargs["temperature"] = self.cfg.temperature
        if schema:
            kwargs["response_format"] = {"type": "json_object"}

        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


class OpenAIProvider(OpenAICompatibleProvider):
    default_base_url = None  # SDK default


class GroqProvider(OpenAICompatibleProvider):
    default_base_url = "https://api.groq.com/openai/v1"


PROVIDER_CLASSES = {"gemini": GeminiProvider, "groq": GroqProvider, "openai": OpenAIProvider}