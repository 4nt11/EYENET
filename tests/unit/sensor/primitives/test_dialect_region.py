"""Unit tests for the dialect_region locale-aware primitive.

Covers: argmax detection, ``unknown`` fallback, margin gate, language gate
(non-Spanish returns None), min-message gate, slot-mapper wiring.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from behave_text.spec import PRIMITIVE_REGISTRY

from eyenet.sensor.primitives import dialect_region as dr
from eyenet.sensor.primitives._regional_markers import REGIONAL_MARKERS


def _ts(i: int = 0) -> datetime:
    return datetime(2026, 5, 1, 12, i, tzinfo=UTC)


def _corpus_bodies(
    texts: list[str],
    start_offset: int = 0,
) -> tuple[list[tuple[datetime, UUID, str]], dict[str, str]]:
    """Build a (corpus, bodies) pair from plaintext strings."""
    corpus: list[tuple[datetime, UUID, str]] = []
    bodies: dict[str, str] = {}
    for i, text in enumerate(texts):
        ref = f"ref:{start_offset + i}"
        corpus.append((_ts(i), uuid4(), ref))
        bodies[ref] = text
    return corpus, bodies


def _repeat(text: str, n: int) -> list[str]:
    return [text] * n


# ─── registry contract ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_primitive_in_behave_text_registry() -> None:
    assert dr.PRIMITIVE_NAME in PRIMITIVE_REGISTRY


@pytest.mark.unit
def test_registered_in_eyenet_primitives() -> None:
    from eyenet.sensor.primitives import PRIMITIVES

    names = {p.name for p in PRIMITIVES}
    assert dr.PRIMITIVE_NAME in names


@pytest.mark.unit
def test_requires_full_corpus() -> None:
    from eyenet.sensor.primitives import PRIMITIVES

    spec = next(p for p in PRIMITIVES if p.name == dr.PRIMITIVE_NAME)
    assert spec.requires_full_corpus is True


# ─── min-message gate ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_too_few_messages_returns_none() -> None:
    corpus, bodies = _corpus_bodies(_repeat("che boludo", dr.MIN_MESSAGES - 1))
    assert dr.compute(corpus=corpus, bodies=bodies) is None


@pytest.mark.unit
def test_exactly_min_messages_does_not_return_none_for_spanish() -> None:
    # Spanish text, enough messages — should produce an Observation (maybe unknown)
    corpus, bodies = _corpus_bodies(_repeat("de la que el en", dr.MIN_MESSAGES))
    obs = dr.compute(corpus=corpus, bodies=bodies)
    assert obs is not None


# ─── language gate ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_english_corpus_returns_none() -> None:
    texts = _repeat("the cat sat on the mat and the dog ran away", dr.MIN_MESSAGES)
    corpus, bodies = _corpus_bodies(texts)
    assert dr.compute(corpus=corpus, bodies=bodies) is None


# ─── unknown fallback ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_ambiguous_spanish_returns_unknown() -> None:
    # Generic Spanish with no regional markers → unknown
    texts = _repeat("de la que el en y a los se las un por con una su para es muy", dr.MIN_MESSAGES)
    corpus, bodies = _corpus_bodies(texts)
    obs = dr.compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.value == dr.UNKNOWN_SENTINEL
    assert obs.primitive == dr.PRIMITIVE_NAME


# ─── region detection ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_argentine_markers_detected() -> None:
    # Use markers known to be in the generated INGEOTEC-derived set
    marker_text = " ".join(["de la que el en"] * 3 + ["che boludo posta laburo quilombo guita"])
    texts = _repeat(marker_text, dr.MIN_MESSAGES)
    corpus, bodies = _corpus_bodies(texts)
    obs = dr.compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.value == "es-AR"
    assert obs.primitive == dr.PRIMITIVE_NAME


@pytest.mark.unit
def test_mexican_markers_detected() -> None:
    marker_text = " ".join(["de la que el en"] * 3 + ["chido chingo chingon culero neta chinga"])
    texts = _repeat(marker_text, dr.MIN_MESSAGES)
    corpus, bodies = _corpus_bodies(texts)
    obs = dr.compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.value == "es-MX"


@pytest.mark.unit
def test_chilean_markers_detected() -> None:
    marker_text = " ".join(["de la que el en"] * 3 + ["weon altiro aweonao callampa fome cabros"])
    texts = _repeat(marker_text, dr.MIN_MESSAGES)
    corpus, bodies = _corpus_bodies(texts)
    obs = dr.compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.value == "es-CL"


@pytest.mark.unit
def test_venezuelan_markers_detected() -> None:
    ve_markers = "chamo marico arrecho arrecha bachaqueo chamos"
    marker_text = " ".join(["de la que el en"] * 3 + [ve_markers])
    texts = _repeat(marker_text, dr.MIN_MESSAGES)
    corpus, bodies = _corpus_bodies(texts)
    obs = dr.compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.value == "es-VE"


@pytest.mark.unit
def test_spain_markers_detected() -> None:
    es_markers = "ostia mola guay chaval cojones gilipollas flipando"
    marker_text = " ".join(["de la que el en"] * 3 + [es_markers])
    texts = _repeat(marker_text, dr.MIN_MESSAGES)
    corpus, bodies = _corpus_bodies(texts)
    obs = dr.compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.value == "es-ES"


# ─── margin gate ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_tied_regions_return_unknown() -> None:
    # Match marker counts AR vs MX so margin < CONFIDENCE_MARGIN → unknown.
    # We compute the actual marker-set overlap to keep this self-consistent
    # with whatever markers the generator emits.
    from eyenet.sensor.primitives._regional_markers import REGIONAL_MARKERS

    ar = sorted(REGIONAL_MARKERS["es-AR"])[:4]
    mx = sorted(REGIONAL_MARKERS["es-MX"])[:4]
    base = "de la que el en y a los"
    mixed = f"{base} {' '.join(ar)} {' '.join(mx)}"
    texts = _repeat(mixed, dr.MIN_MESSAGES)
    corpus, bodies = _corpus_bodies(texts)
    obs = dr.compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    # The hit counts are equal → top/runner-up ratio = 1.0 < CONFIDENCE_MARGIN
    assert obs.value == dr.UNKNOWN_SENTINEL


# ─── Observation shape ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_observation_source_contains_marker_version_tag() -> None:
    marker_text = " ".join(["de la que el en"] * 3 + ["che boludo posta laburo quilombo"])
    texts = _repeat(marker_text, dr.MIN_MESSAGES)
    corpus, bodies = _corpus_bodies(texts)
    obs = dr.compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert dr.MARKER_VERSION_TAG in obs.source


@pytest.mark.unit
def test_observation_confidence_in_range() -> None:
    marker_text = " ".join(["de la que el en"] * 3 + ["che boludo posta laburo quilombo"])
    texts = _repeat(marker_text, dr.MIN_MESSAGES)
    corpus, bodies = _corpus_bodies(texts)
    obs = dr.compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert 0.0 <= obs.confidence <= 1.0


# ─── slot mapper wiring ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_slot_mapper_routes_dialect_region() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4 as _uuid4

    from eyenet.contracts.enums import ValueKind
    from eyenet.contracts.observation import ObservationRow
    from eyenet.engine.slot_mapper import observation_to_slot

    # FREE_STRING values land in value_hash per the sensor's mapping convention
    # (eyenet/sensor/stylometric.py:_obs_to_row).
    row = ObservationRow(
        actor_id=_uuid4(),
        primitive_namespace="lexical",
        primitive_name=dr.PRIMITIVE_NAME,
        primitive_version=dr.PRIMITIVE_VERSION,
        value_kind=ValueKind.HASH,
        value_hash="es-CL",
        observed_at=datetime.now(tz=UTC),
        sensor_instance="sensor_test",
    )
    mapping = observation_to_slot(row)
    assert mapping is not None
    assert mapping.block_name == "lexical_summary"
    assert mapping.slot_key == "dialect_region"
    assert mapping.slot_dict["value"] == "es-CL"


# ─── regional_markers integrity ──────────────────────────────────────────────


@pytest.mark.unit
def test_all_marker_keys_are_valid_bcp47() -> None:
    for key in REGIONAL_MARKERS:
        lang, sep, region = key.partition("-")
        assert sep == "-", f"key {key!r} is not BCP-47 xx-YY format"
        assert len(lang) == 2, f"language subtag {lang!r} should be 2 chars"
        assert len(region) == 2, f"region subtag {region!r} should be 2 chars"


@pytest.mark.unit
def test_marker_sets_are_nonempty() -> None:
    for key, markers in REGIONAL_MARKERS.items():
        assert len(markers) > 0, f"empty marker set for {key!r}"


@pytest.mark.unit
def test_no_whitespace_in_token_markers() -> None:
    # Markers with whitespace (multiword) won't match single-token tokenizer
    import re as _re

    tokenizer_re = _re.compile(
        r"[a-záéíóúüñàèìòùâêîôûäëïöü']+",
        _re.IGNORECASE,
    )
    for key, markers in REGIONAL_MARKERS.items():
        for m in markers:
            tokens = tokenizer_re.findall(m)
            if len(tokens) > 1:
                import warnings

                warnings.warn(
                    f"{key}: multi-word marker {m!r} won't match",
                    stacklevel=1,
                )
