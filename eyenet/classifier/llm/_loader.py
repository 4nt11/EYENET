"""Load + validate the operator-editable LLM advisory config (TOML).

Mirrors :mod:`eyenet.classifier.presidio._loader`: a strict pydantic shape
(``extra="forbid"``) with eager validation, an env override
(``EYENET_LLM_CONFIG``), and a bundled default. The *provider* itself is chosen
by ``EYENET_LLM_PROVIDER`` in :mod:`.factory` (env, exactly like
``EYENET_STORAGE_TYPE`` for storage) — this file configures the *connection* to
whichever provider was selected: model, endpoint, timeouts, retry budget, and
the input/output bounds that defend against runaway cost and oversized output.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

import structlog
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["LLM_CONFIG_ENV", "LlmConfig", "load_llm_config"]

_log = structlog.get_logger()

LLM_CONFIG_ENV = "EYENET_LLM_CONFIG"
_BUNDLED_DEFAULT = Path(__file__).parent / "_default_llm.toml"


class _LlmConfigFile(BaseModel):
    """Parsed shape of an LLM-config TOML file."""

    model_config = ConfigDict(extra="forbid")

    config_version: str
    model: str
    endpoint: str = "http://127.0.0.1:11434"
    connect_timeout_s: float = Field(default=5.0, gt=0.0)
    request_timeout_s: float = Field(default=60.0, gt=0.0)
    max_attempts: int = Field(default=3, ge=1, le=10)
    max_text_chars: int = Field(default=12000, gt=0)
    max_summary_chars: int = Field(default=2000, gt=0)
    max_indicators: int = Field(default=20, ge=0)
    # Egress guard: a non-loopback endpoint would send (sub-CLASSIFIED) document
    # text off-host. Default-deny; an operator must opt in explicitly. Only local
    # Ollama ships today — this is the gate a future cloud provider must clear.
    allow_remote: bool = False


@dataclass(frozen=True, slots=True)
class LlmConfig:
    """An immutable, validated LLM advisory configuration."""

    config_version: str
    model: str
    endpoint: str
    connect_timeout_s: float
    request_timeout_s: float
    max_attempts: int
    max_text_chars: int
    max_summary_chars: int
    max_indicators: int
    allow_remote: bool


def _resolve_path(path: Path | None) -> Path:
    """Explicit arg wins; else the env override; else the bundled default."""
    if path is not None:
        return path
    env = os.environ.get(LLM_CONFIG_ENV)
    if env:
        return Path(env)
    return _BUNDLED_DEFAULT


def load_llm_config(path: Path | None = None) -> LlmConfig:
    """Load and validate the LLM config.

    Raises :class:`FileNotFoundError` if the file is absent and
    :class:`ValueError` (via pydantic) on any shape/range error.
    """
    resolved = _resolve_path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"LLM config not found: {resolved}")

    parsed = _LlmConfigFile.model_validate(tomllib.loads(resolved.read_text("utf-8")))

    _log.info(
        "classify.llm_config_loaded",
        config_version=parsed.config_version,
        model=parsed.model,
        endpoint=parsed.endpoint,
        max_attempts=parsed.max_attempts,
        allow_remote=parsed.allow_remote,
        source=str(resolved),
    )
    return LlmConfig(
        config_version=parsed.config_version,
        model=parsed.model,
        endpoint=parsed.endpoint,
        connect_timeout_s=parsed.connect_timeout_s,
        request_timeout_s=parsed.request_timeout_s,
        max_attempts=parsed.max_attempts,
        max_text_chars=parsed.max_text_chars,
        max_summary_chars=parsed.max_summary_chars,
        max_indicators=parsed.max_indicators,
        allow_remote=parsed.allow_remote,
    )
