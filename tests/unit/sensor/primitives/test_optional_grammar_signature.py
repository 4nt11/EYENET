"""Unit tests for the lexical.optional_grammar_signature primitive."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from behave_text.spec import PRIMITIVE_REGISTRY

from eyenet.engine.slot_mapper import _LANGUAGE_SUFFIX_PRIMITIVES, _SLOT_MAP
from eyenet.sensor.primitives import optional_grammar_signature as ogs


def _corpus_bodies(texts: list[str]) -> tuple[list[tuple[datetime, UUID, str]], dict[str, str]]:
    prefix = uuid4().hex[:8]
    corpus: list[tuple[datetime, UUID, str]] = []
    bodies: dict[str, str] = {}
    for i, text in enumerate(texts):
        ref = f"{prefix}:ref:{i}"
        corpus.append((datetime(2026, 5, 1, 12, i, tzinfo=UTC), uuid4(), ref))
        bodies[ref] = text
    return corpus, bodies


# Subjunctive + leísmo-flavored body (heavy clitic_le usage)
_LEISMO_BODY = (
    "Le dije que se fuera de aqui. Le pedi que viniera mañana. "
    "Le hablamos cuando llego. Le vi en el parque. Le encontre dormido. "
    "Quiero que vengas pronto. Si tuviera tiempo te ayudaria. Ojala llueva. "
    "Hubiera querido que vieras la pelicula. Espero que estes bien. "
    "Le compre un regalo para su cumple. Le mande un mensaje ayer."
)
# Compound-past heavy body (Spain-style register)
_COMPOUND_BODY = (
    "He comido pizza esta tarde. Hemos visto la pelicula nueva. "
    "Habian llegado temprano. Habiamos cenado juntos. "
    "Han traido el regalo. Hemos hablado mucho hoy. "
    "He estado pensando en eso. Hemos decidido salir mañana. "
    "Habia escrito una carta. Habiamos comprado todo lo necesario. "
    "Han llegado los invitados. Hemos preparado la cena."
)


# ─── registry contract ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_in_behave_text_registry() -> None:
    assert ogs.PRIMITIVE_NAME in PRIMITIVE_REGISTRY


@pytest.mark.unit
def test_registered_in_eyenet_primitives() -> None:
    from eyenet.sensor.primitives import PRIMITIVES

    spec = next(p for p in PRIMITIVES if p.name == ogs.PRIMITIVE_NAME)
    assert spec.requires_full_corpus is True


@pytest.mark.unit
def test_slot_mapper_wiring() -> None:
    assert _SLOT_MAP[ogs.PRIMITIVE_NAME] == (
        "lexical_summary",
        "optional_grammar_signature",
    )


@pytest.mark.unit
def test_in_language_suffix_whitelist() -> None:
    assert ogs.PRIMITIVE_NAME in _LANGUAGE_SUFFIX_PRIMITIVES


# ─── gates ───────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_empty_corpus_returns_none() -> None:
    assert ogs.compute(corpus=[], bodies={}) is None


@pytest.mark.unit
def test_too_few_tokens_returns_none() -> None:
    corpus, bodies = _corpus_bodies(["hola amigo"])
    assert ogs.compute(corpus=corpus, bodies=bodies) is None


# ─── output shape ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_emits_simhash_for_spanish_corpus() -> None:
    corpus, bodies = _corpus_bodies([_LEISMO_BODY] * 6)
    obs = ogs.compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert isinstance(obs.value, str)
    assert len(obs.value) == 16


@pytest.mark.unit
def test_source_label_carries_ruleset_and_language() -> None:
    corpus, bodies = _corpus_bodies([_LEISMO_BODY] * 6)
    obs = ogs.compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert ogs.RULESET_TAG in obs.source
    assert obs.source.endswith("#es")


@pytest.mark.unit
def test_determinism() -> None:
    corpus, bodies = _corpus_bodies([_LEISMO_BODY] * 6)
    a = ogs.compute(corpus=corpus, bodies=bodies)
    b = ogs.compute(corpus=corpus, bodies=bodies)
    assert a is not None
    assert b is not None
    assert a.value == b.value


@pytest.mark.unit
def test_discrimination_different_choice_point_patterns() -> None:
    """Compound-past-heavy vs leísmo+subjunctive-heavy → distinct simhash."""
    c1, b1 = _corpus_bodies([_LEISMO_BODY] * 6)
    c2, b2 = _corpus_bodies([_COMPOUND_BODY] * 6)
    a = ogs.compute(corpus=c1, bodies=b1)
    b = ogs.compute(corpus=c2, bodies=b2)
    assert a is not None
    assert b is not None
    assert a.value != b.value
