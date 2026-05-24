"""Unit tests for the stylometric.pos_ngram_signature primitive."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from behave_text.spec import PRIMITIVE_REGISTRY

from eyenet.engine.slot_mapper import _LANGUAGE_SUFFIX_PRIMITIVES, _SLOT_MAP
from eyenet.sensor.primitives import pos_ngram_signature as png

# Spanish chat-style paragraph; long enough to clear MIN_TOKENS when repeated.
_ES_PARA = (
    "Tengo una casita en la playa. Habiamos comido cuando le dije que se fuera. "
    "El perrito ladra mucho. La casucha del barrio es un desastre. "
    "Le hicimos un golazo. Cuando llegara mi hermano le voy a contar. "
    "Hubiera querido que vieras la pelicula. Si tuviera mas tiempo iria al cine. "
    "Mi vecino habla del partido. La gente del barrio se conoce hace anos."
)
_EN_PARA = (
    "I went to the store this morning. The cat was sleeping on the couch. "
    "We had lunch together yesterday. The weather is nice today. "
    "He told me that he would come later. I have not seen the movie yet."
)


def _corpus_bodies(texts: list[str]) -> tuple[list[tuple[datetime, UUID, str]], dict[str, str]]:
    # Per-call UUID prefix so two corpora built in the same test (e.g. for
    # discrimination tests) never share refs and never collide in the
    # kernel's single-slot memo.
    prefix = uuid4().hex[:8]
    corpus: list[tuple[datetime, UUID, str]] = []
    bodies: dict[str, str] = {}
    for i, text in enumerate(texts):
        ref = f"{prefix}:ref:{i}"
        corpus.append((datetime(2026, 5, 1, 12, i, tzinfo=UTC), uuid4(), ref))
        bodies[ref] = text
    return corpus, bodies


# ─── registry contract ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_in_behave_text_registry() -> None:
    assert png.PRIMITIVE_NAME in PRIMITIVE_REGISTRY


@pytest.mark.unit
def test_registered_in_eyenet_primitives() -> None:
    from eyenet.sensor.primitives import PRIMITIVES

    spec = next(p for p in PRIMITIVES if p.name == png.PRIMITIVE_NAME)
    assert spec.requires_full_corpus is True


@pytest.mark.unit
def test_slot_mapper_wiring() -> None:
    assert _SLOT_MAP[png.PRIMITIVE_NAME] == (
        "stylometric_summary",
        "pos_ngram_signature",
    )


@pytest.mark.unit
def test_in_language_suffix_whitelist() -> None:
    assert png.PRIMITIVE_NAME in _LANGUAGE_SUFFIX_PRIMITIVES


# ─── gates ───────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_empty_corpus_returns_none() -> None:
    assert png.compute(corpus=[], bodies={}) is None


@pytest.mark.unit
def test_non_spanish_returns_none() -> None:
    corpus, bodies = _corpus_bodies([_EN_PARA] * 5)
    assert png.compute(corpus=corpus, bodies=bodies) is None


@pytest.mark.unit
def test_too_few_tokens_returns_none() -> None:
    # A single short Spanish sentence — well under MIN_TOKENS=200.
    corpus, bodies = _corpus_bodies(["hola amigo, como estas"])
    assert png.compute(corpus=corpus, bodies=bodies) is None


# ─── output shape ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_emits_observation_for_spanish_corpus() -> None:
    corpus, bodies = _corpus_bodies([_ES_PARA] * 5)
    obs = png.compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.primitive == png.PRIMITIVE_NAME
    assert isinstance(obs.value, str)
    assert len(obs.value) == 16  # 64-bit hex
    assert 0.0 <= obs.confidence <= 1.0


@pytest.mark.unit
def test_source_label_carries_tagger_and_language_suffix() -> None:
    corpus, bodies = _corpus_bodies([_ES_PARA] * 5)
    obs = png.compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert png.TAGGER_TAG in obs.source
    assert obs.source.endswith("#es")


# ─── determinism + discrimination ────────────────────────────────────────────


@pytest.mark.unit
def test_determinism_same_corpus_same_hash() -> None:
    corpus, bodies = _corpus_bodies([_ES_PARA] * 5)
    a = png.compute(corpus=corpus, bodies=bodies)
    b = png.compute(corpus=corpus, bodies=bodies)
    assert a is not None
    assert b is not None
    assert a.value == b.value


@pytest.mark.unit
def test_discrimination_distinct_pos_patterns() -> None:
    """Two corpora with markedly different POS rhythms produce different
    fingerprints. We don't assert Hamming distance — just inequality."""
    # Both corpora include enough Spanish anchors to clear detect_language;
    # difference between them is POS density (noun/adj vs verb-leading).
    nominal_heavy = (
        "La casa es grande y el perro es feliz. El coche es rojo y la mesa "
        "es redonda. El libro es nuevo y la silla es vieja. La puerta es "
        "abierta y la ventana es sucia. El tren es rapido y el avion es "
        "ruidoso. El camion es pesado y la bicicleta es verde. La moto es "
        "azul y el barco es grande. El caballo es blanco."
    )
    verb_heavy = (
        "En la casa corro y hablo. Por la calle como y duermo. Con el "
        "amigo trabajo y estudio. Para el examen leo y escribo. En la "
        "noche pienso y vuelvo. Por la mañana salgo y regreso. Con los "
        "vecinos camino y hablo. En el parque subo y bajo. Con un libro "
        "entro y salgo. Por su culpa vivo y muero. Para una vida gano "
        "y pierdo. En la oficina busco y encuentro."
    )
    c1, b1 = _corpus_bodies([nominal_heavy] * 15)
    c2, b2 = _corpus_bodies([verb_heavy] * 15)
    a = png.compute(corpus=c1, bodies=b1)
    b = png.compute(corpus=c2, bodies=b2)
    assert a is not None
    assert b is not None
    assert a.value != b.value
