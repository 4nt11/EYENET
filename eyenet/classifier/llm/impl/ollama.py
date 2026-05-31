"""Ollama provider — a thin async HTTP transport to a local Ollama daemon.

The model runs in its OWN process (the Ollama daemon); we only POST text and
read text back over ``httpx``. No tools, no function-calling, no file handles —
``tools`` is never sent. This is why the stage needs no nsjail: there is no
untrusted-code-execution surface, only untrusted output (handled upstream by
:mod:`.._repair` / :mod:`.._sanitize`).

This module is the live I/O boundary: it is coverage-omitted (like the live
collectors) because it cannot be exercised without a running daemon. Its only
job is to translate Ollama's wire/HTTP errors into the provider-neutral
:class:`ProviderUnavailable` / :class:`ProviderTimeout`, keeping all logic in the
unit-tested, provider-agnostic :mod:`.._advise` layer. The integration test
(``test_llm_real.py``) exercises it against a real daemon when one is present.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx

from eyenet.classifier.llm.base import (
    BaseProvider,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from eyenet.classifier.llm.base import Msg

__all__ = ["OllamaProvider"]


def _is_loopback(endpoint: str) -> bool:
    """True iff the endpoint host is loopback (``localhost`` or a loopback IP)."""
    host = urlsplit(endpoint).hostname
    if host is None:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class OllamaProvider(BaseProvider):
    """Talk to a local Ollama daemon via its ``/api/chat`` endpoint."""

    def __init__(
        self,
        *,
        model: str,
        endpoint: str = "http://127.0.0.1:11434",
        connect_timeout_s: float = 5.0,
    ) -> None:
        self._model = model
        self._endpoint = endpoint.rstrip("/")
        self._connect_timeout_s = connect_timeout_s

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def model(self) -> str:
        return self._model

    @property
    def is_local(self) -> bool:
        return _is_loopback(self._endpoint)

    async def generate(
        self,
        messages: Sequence[Msg],
        *,
        json_schema: dict[str, object],
        timeout_s: float,
    ) -> str:
        """POST one chat completion; return the raw assistant text.

        ``format`` carries the JSON schema (structured-output grammar); ``tools``
        is deliberately never sent; ``stream`` is off so we get one body.
        """
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "format": json_schema,
            "options": {"temperature": 0},
        }
        timeout = httpx.Timeout(timeout_s, connect=self._connect_timeout_s)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{self._endpoint}/api/chat", json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except (httpx.HTTPStatusError, httpx.HTTPError) as exc:
            raise ProviderUnavailableError(str(exc)) from exc

        message = body.get("message") if isinstance(body, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ProviderUnavailableError("malformed ollama response envelope")
        return content
