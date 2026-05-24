"""Unit tests for the lexical.evaluative_morphology_density primitive."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from behave_text.spec import PRIMITIVE_REGISTRY

from eyenet.engine.slot_mapper import _LANGUAGE_SUFFIX_PRIMITIVES, _SLOT_MAP
from eyenet.sensor.primitives import evaluative_morphology_density as emd


def _corpus_bodies(texts: list[str]) -> tuple[list[tuple[datetime, UUID, str]], dict[str, str]]:
    prefix = uuid4().hex[:8]
    corpus: list[tuple[datetime, UUID, str]] = []
    bodies: dict[str, str] = {}
    for i, text in enumerate(texts):
        ref = f"{prefix}:ref:{i}"
        corpus.append((datetime(2026, 5, 1, 12, i, tzinfo=UTC), uuid4(), ref))
        bodies[ref] = text
    return corpus, bodies


_NEUTRAL_NOUN_BODY = (
    "El perro corre en el parque. La gente camina por la calle. "
    "El coche pasa por la avenida. La casa esta en la esquina. "
    "El gato duerme en el sofa. La mesa esta en la cocina. "
    "El libro esta en la biblioteca. La silla esta junto a la ventana."
)
_DIMINUTIVE_HEAVY_BODY = (
    "El perrito ladra en el parquecito. El gatito duerme en el sofacito. "
    "La casita esta en la esquina. El cochecito es nuevo. "
    "La mesita es chiquita. La sillita es bonita. "
    "El librito es interesante. La ventanita esta abierta."
)


# ─── registry contract ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_in_behave_text_registry() -> None:
    assert emd.PRIMITIVE_NAME in PRIMITIVE_REGISTRY


@pytest.mark.unit
def test_registered_in_eyenet_primitives() -> None:
    from eyenet.sensor.primitives import PRIMITIVES

    spec = next(p for p in PRIMITIVES if p.name == emd.PRIMITIVE_NAME)
    assert spec.requires_full_corpus is True


@pytest.mark.unit
def test_slot_mapper_wiring() -> None:
    assert _SLOT_MAP[emd.PRIMITIVE_NAME] == (
        "lexical_summary",
        "evaluative_morphology_density",
    )


@pytest.mark.unit
def test_not_in_language_suffix_whitelist() -> None:
    """Density is numeric — no per-language threshold lookup branch."""
    assert emd.PRIMITIVE_NAME not in _LANGUAGE_SUFFIX_PRIMITIVES


# ─── gates ───────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_empty_corpus_returns_none() -> None:
    assert emd.compute(corpus=[], bodies={}) is None


@pytest.mark.unit
def test_too_few_target_tokens_returns_none() -> None:
    corpus, bodies = _corpus_bodies(["hola amigo"])
    assert emd.compute(corpus=corpus, bodies=bodies) is None


# ─── output shape + range ────────────────────────────────────────────────────


@pytest.mark.unit
def test_emits_density_in_unit_range() -> None:
    corpus, bodies = _corpus_bodies([_DIMINUTIVE_HEAVY_BODY] * 10)
    obs = emd.compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert isinstance(obs.value, float)
    assert 0.0 <= obs.value <= 1.0


@pytest.mark.unit
def test_diminutive_heavy_corpus_higher_density_than_neutral() -> None:
    cn, bn = _corpus_bodies([_NEUTRAL_NOUN_BODY] * 10)
    cd, bd = _corpus_bodies([_DIMINUTIVE_HEAVY_BODY] * 10)
    neutral_obs = emd.compute(corpus=cn, bodies=bn)
    dim_obs = emd.compute(corpus=cd, bodies=bd)
    assert neutral_obs is not None
    assert dim_obs is not None
    assert dim_obs.value > neutral_obs.value


@pytest.mark.unit
def test_source_label_includes_ruleset_tag() -> None:
    corpus, bodies = _corpus_bodies([_DIMINUTIVE_HEAVY_BODY] * 10)
    obs = emd.compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert emd.RULESET_TAG in obs.source
