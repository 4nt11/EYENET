"""Verifier Protocol contract — every REGISTRY member implements the surface."""

from __future__ import annotations

import pytest

from eyenet.verifier.verifiers import REGISTRY, Verifier, default_registry


@pytest.mark.unit
def test_registry_non_empty() -> None:
    assert len(REGISTRY) >= 1


@pytest.mark.unit
def test_registry_names_unique() -> None:
    names = [v.name for v in REGISTRY]
    assert len(names) == len(set(names)), f"duplicate verifier names: {names}"


@pytest.mark.unit
@pytest.mark.parametrize("verifier", REGISTRY, ids=[v.name for v in REGISTRY])
def test_verifier_protocol_fields(verifier: Verifier) -> None:
    assert isinstance(verifier.name, str)
    assert verifier.name
    assert isinstance(verifier.version, str)
    assert verifier.version
    assert isinstance(verifier.requires_language, bool)
    assert isinstance(verifier.min_messages_per_actor, int)
    assert verifier.min_messages_per_actor >= 1


@pytest.mark.unit
@pytest.mark.parametrize("verifier", REGISTRY, ids=[v.name for v in REGISTRY])
def test_verifier_skips_on_short_corpus(verifier: Verifier) -> None:
    """Below min_messages_per_actor → skipped=True, score=0, confidence=0."""
    short = ["hola"] * 2
    result = verifier.verify(short, short, language="es")
    assert result.skipped is True
    assert result.score == 0.0
    assert result.confidence == 0.0
    assert result.skip_reason


@pytest.mark.unit
def test_default_registry_with_empty_pool_returns_same_count() -> None:
    """default_registry() must always produce the canonical set, pool or no pool."""
    assert len(default_registry([])) == len(REGISTRY)
    assert len(default_registry([["a"] * 60, ["b"] * 60])) == len(REGISTRY)
