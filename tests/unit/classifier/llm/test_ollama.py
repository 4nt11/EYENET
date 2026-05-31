"""OllamaProvider props + the loopback egress check.

The transport's HTTP path needs a live daemon (covered by the integration test
+ coverage-omitted), but is_local is pure, security-relevant logic — it is the
egress guard advise() relies on — so it is unit-tested here without any network.
"""

from __future__ import annotations

import pytest

from eyenet.classifier.llm.impl.ollama import OllamaProvider

pytestmark = pytest.mark.unit


def test_name_and_model() -> None:
    p = OllamaProvider(model="llama3.1")
    assert p.name == "ollama"
    assert p.model == "llama3.1"


@pytest.mark.parametrize(
    ("endpoint", "expected_local"),
    [
        ("http://127.0.0.1:11434", True),
        ("http://localhost:11434", True),
        ("http://[::1]:11434", True),
        ("http://10.0.0.5:11434", False),
        ("http://ollama.example.com:11434", False),
        ("http://192.168.1.10", False),
    ],
)
def test_is_local_detects_loopback(endpoint: str, expected_local: bool) -> None:
    assert OllamaProvider(model="m", endpoint=endpoint).is_local is expected_local
