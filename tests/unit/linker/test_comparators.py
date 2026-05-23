"""Registry shape, threshold defaults, and slot value extraction for comparators."""

from __future__ import annotations

import pytest

from eyenet.contracts._base import TraceContext, _new_uuid7
from eyenet.contracts.attribution import ProfileCurrentEnvelope
from eyenet.linker.comparators import REGISTRY, select_for_slot
from eyenet.linker.comparators._base import ComparisonResult
from eyenet.linker.comparators.char_ngram_simhash_hamming import CharNgramSimhashHamming
from eyenet.linker.comparators.function_word_simhash_hamming import FunctionWordSimhashHamming

_CLOSE_HASH = "0000000000000001"
_FAR_HASH = "ffffffffffffffff"
_BASE_HASH = "0000000000000000"


@pytest.mark.unit
def test_registry_is_nonempty() -> None:
    assert len(REGISTRY) >= 2


@pytest.mark.unit
def test_registry_contains_function_word() -> None:
    names = {c.name for c in REGISTRY}
    assert "function_word_simhash_hamming" in names


@pytest.mark.unit
def test_registry_contains_char_ngram() -> None:
    names = {c.name for c in REGISTRY}
    assert "char_ngram_simhash_hamming" in names


@pytest.mark.unit
def test_all_registry_entries_implement_protocol() -> None:
    required = {"name", "version", "slot_path", "primitive_name", "default_threshold"}
    for comp in REGISTRY:
        missing = required - set(dir(comp))
        assert not missing, f"{comp} missing: {missing}"


@pytest.mark.unit
def test_function_word_default_threshold() -> None:
    assert FunctionWordSimhashHamming.default_threshold == 8


@pytest.mark.unit
def test_char_ngram_default_threshold() -> None:
    assert CharNgramSimhashHamming.default_threshold == 10


@pytest.mark.unit
def test_select_for_slot_function_word() -> None:
    slot = "stylometric_summary.function_word_simhash"
    found = select_for_slot(slot)
    assert found is not None
    assert found.name == "function_word_simhash_hamming"


@pytest.mark.unit
def test_select_for_slot_char_ngram() -> None:
    slot = "stylometric_summary.char_ngram_simhash"
    found = select_for_slot(slot)
    assert found is not None
    assert found.name == "char_ngram_simhash_hamming"


@pytest.mark.unit
def test_select_for_slot_unknown_returns_none() -> None:
    assert select_for_slot("unknown.slot") is None


@pytest.mark.unit
def test_compare_within_threshold_yields_true() -> None:
    # distance = 1 bit, threshold = 8
    result = FunctionWordSimhashHamming.compare(_BASE_HASH, _CLOSE_HASH, 8)
    assert result.within_threshold is True
    assert result.distance == 1
    assert 0.0 <= result.score <= 1.0


@pytest.mark.unit
def test_compare_beyond_threshold_yields_false() -> None:
    # distance = 64 bits, threshold = 8
    result = FunctionWordSimhashHamming.compare(_BASE_HASH, _FAR_HASH, 8)
    assert result.within_threshold is False


@pytest.mark.unit
def test_compare_score_is_one_at_zero_distance() -> None:
    result = FunctionWordSimhashHamming.compare(_BASE_HASH, _BASE_HASH, 8)
    assert result.score == pytest.approx(1.0)
    assert result.distance == 0
    assert result.within_threshold is True


@pytest.mark.unit
def test_compare_returns_comparison_result() -> None:
    result = FunctionWordSimhashHamming.compare(_BASE_HASH, _CLOSE_HASH, 8)
    assert isinstance(result, ComparisonResult)


def _profile_envelope(**stylometric: object) -> ProfileCurrentEnvelope:
    from datetime import UTC, datetime

    tc = TraceContext(traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01")
    return ProfileCurrentEnvelope(
        profile_id=_new_uuid7(),
        actor_id=_new_uuid7(),
        version=1,
        role_confidence=0.5,
        stylometric_summary=dict(stylometric),
        derived_at=datetime(2026, 5, 1, tzinfo=UTC),
        derived_from_observation_count=1,
        trace_context=tc,
    )


@pytest.mark.unit
def test_slot_value_extraction_function_word() -> None:
    env = _profile_envelope(function_word_simhash={"value": "deadbeefcafebabe"})
    val = FunctionWordSimhashHamming.slot_value(env)
    assert val == "deadbeefcafebabe"


@pytest.mark.unit
def test_slot_value_returns_none_when_missing() -> None:
    env = _profile_envelope()
    val = FunctionWordSimhashHamming.slot_value(env)
    assert val is None


@pytest.mark.unit
def test_slot_value_char_ngram() -> None:
    env = _profile_envelope(char_ngram_simhash={"value": "1122334455667788"})
    val = CharNgramSimhashHamming.slot_value(env)
    assert val == "1122334455667788"
