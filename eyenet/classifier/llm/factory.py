"""Env-dispatched provider factory — the single backend-selection point.

Mirrors :func:`eyenet.storage.factory.get_repository` verbatim: read
``EYENET_LLM_PROVIDER`` (default ``"ollama"``), lazily import the one selected
backend (so a future heavy-SDK provider never loads unless chosen), and forward
``**kwargs`` to it. Adding a provider is one branch here — never an edit to every
caller. Production code imports :func:`get_provider`, never a concrete provider.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .base import BaseProvider

__all__ = ["get_provider"]


def get_provider(**kwargs: Any) -> BaseProvider:
    """Instantiate the provider selected by ``EYENET_LLM_PROVIDER``.

    Keyword arguments (``model``, ``endpoint``, timeouts) are forwarded to the
    concrete provider — see :func:`._advise.advise`, which sources them from the
    loaded :class:`._loader.LlmConfig`.
    """
    provider = os.environ.get("EYENET_LLM_PROVIDER", "ollama").lower()
    if provider == "ollama":
        from eyenet.classifier.llm.impl.ollama import OllamaProvider  # noqa: PLC0415

        return OllamaProvider(**kwargs)
    raise ValueError(f"Unsupported LLM provider: {provider}")
