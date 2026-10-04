"""Loads and validates llm.yaml into ModelConfig objects."""
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

DEFAULT_CONFIG_PATH = ROOT / "config" / "llm.yaml"
PROVIDERS = {"gemini", "groq", "openai"}

_KNOWN_KEYS = {"provider", "model", "api_key_env", "temperature", "max_tokens", "base_url"}


class LLMConfigError(Exception):
    pass


@dataclass
class ModelConfig:
    name: str
    provider: str
    model: str
    api_key: str | None = None
    api_key_env: str | None = None
    temperature: float | None = None
    max_tokens: int = 4096
    base_url: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class LLMSettings:
    default: str
    fallback: list[str]
    models: dict[str, ModelConfig]


def load_settings(path: Path | str | None = None) -> LLMSettings:
    path = Path(path or os.environ.get("LLM_CONFIG") or DEFAULT_CONFIG_PATH)
    if not path.exists():
        raise LLMConfigError(f"LLM config not found: {path}")

    raw = yaml.safe_load(path.read_text()) or {}
    raw_models = raw.get("models") or {}
    if not raw_models:
        raise LLMConfigError(f"No models defined in {path}")

    models: dict[str, ModelConfig] = {}
    for name, m in raw_models.items():
        provider = str(m.get("provider", "")).lower()
        if provider not in PROVIDERS:
            raise LLMConfigError(
                f"Model '{name}': provider must be one of {sorted(PROVIDERS)}, got '{provider}'"
            )
        if not m.get("model"):
            raise LLMConfigError(f"Model '{name}': missing 'model'")
        if not m.get("api_key_env"):
            raise LLMConfigError(f"Model '{name}': missing 'api_key_env'")

        temperature = m.get("temperature")
        models[name] = ModelConfig(
            name=name,
            provider=provider,
            model=m["model"],
            api_key=os.environ.get(m["api_key_env"]),
            api_key_env=m["api_key_env"],
            temperature=float(temperature) if temperature is not None else None,
            max_tokens=int(m.get("max_tokens", 4096)),
            base_url=m.get("base_url"),
            extra={k: v for k, v in m.items() if k not in _KNOWN_KEYS},
        )

    default = raw.get("default") or next(iter(models))
    fallback = raw.get("fallback") or []
    for ref in [default, *fallback]:
        if ref not in models:
            raise LLMConfigError(f"'{ref}' referenced in default/fallback but not defined in models")

    return LLMSettings(default=default, fallback=list(fallback), models=models)