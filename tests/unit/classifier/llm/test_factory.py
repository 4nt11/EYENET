"""get_provider(): env-dispatched provider factory (mirrors storage)."""

from __future__ import annotations

import pytest

from eyenet.classifier.llm import BaseProvider, get_provider

pytestmark = pytest.mark.unit


def test_default_provider_is_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EYENET_LLM_PROVIDER", raising=False)
    provider = get_provider(model="m")
    assert isinstance(provider, BaseProvider)
    assert provider.name == "ollama"


def test_explicit_ollama_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EYENET_LLM_PROVIDER", "ollama")
    assert get_provider(model="m").name == "ollama"


def test_dispatch_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EYENET_LLM_PROVIDER", "OLLAMA")
    assert get_provider(model="m").name == "ollama"


def test_unknown_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EYENET_LLM_PROVIDER", "definitely-not-real")
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        get_provider(model="m")
