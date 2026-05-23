"""Unit tests for slot_mapper — primitive_name → (block, slot_key, slot_dict)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from eyenet.contracts.enums import ValueKind
from eyenet.contracts.observation import ObservationRow
from eyenet.engine.slot_mapper import observation_to_slot

_TS = datetime(2026, 5, 1, tzinfo=UTC)
_UUID = UUID("00000000-0000-0000-0000-000000000001")


def _row(
    primitive: str, value_kind: ValueKind = ValueKind.HASH, **value_kwargs: Any
) -> ObservationRow:
    return ObservationRow(
        id=_UUID,
        actor_id=_UUID,
        primitive_namespace=primitive.split(".", maxsplit=1)[0],
        primitive_name=primitive,
        primitive_version="0.1",
        value_kind=value_kind,
        observed_at=_TS,
        sensor_instance="test",
        evidence_ref="test:123",
        **value_kwargs,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("primitive", "expected_block", "expected_key"),
    [
        # M2 primitives
        (
            "stylometric.function_word_distribution_top50",
            "stylometric_summary",
            "function_word_simhash",
        ),
        ("stylometric.character_ngram_simhash", "stylometric_summary", "char_ngram_simhash"),
        ("stylometric.distinctive_vocabulary_signature", "lexical_summary", "distinctive_vocab"),
        ("lexical.vocabulary_richness", "lexical_summary", "mattr"),
        # M3 primitives
        ("stylometric.message_length_class", "stylometric_summary", "message_length_class"),
        (
            "stylometric.message_length_variance_class",
            "stylometric_summary",
            "message_length_variance_class",
        ),
        ("stylometric.punctuation_style", "stylometric_summary", "punctuation_style"),
        ("stylometric.typo_signature", "stylometric_summary", "typo_signature"),
        (
            "interaction.conversation_initiation_rate",
            "interaction_summary",
            "conversation_initiation_rate",
        ),
        # M5.5 — meta.* primitives (BEHAVE-TEXT 0.1.2)
        ("meta.total_messages", "temporal_summary", "message_count"),
        ("meta.corpus_span_days", "temporal_summary", "corpus_span_days"),
        ("meta.msg_per_day", "temporal_summary", "msg_per_day"),
        ("meta.active_days", "temporal_summary", "active_days"),
        ("meta.activity_density", "temporal_summary", "activity_density"),
        ("meta.first_seen_ts", "temporal_summary", "first_seen_ts"),
        ("meta.last_seen_ts", "temporal_summary", "last_seen_ts"),
        ("meta.fingerprint_confidence", "temporal_summary", "fingerprint_confidence"),
    ],
)
def test_known_primitives_map_correctly(
    primitive: str, expected_block: str, expected_key: str
) -> None:
    row = _row(primitive, value_kind=ValueKind.HASH, value_hash="deadbeef")
    result = observation_to_slot(row)
    assert result is not None
    assert result.block_name == expected_block
    assert result.slot_key == expected_key


@pytest.mark.unit
def test_unknown_primitive_returns_none() -> None:
    row = _row("unknown.some_future_primitive", value_kind=ValueKind.NUMERIC, value_numeric=0.5)
    assert observation_to_slot(row) is None


@pytest.mark.unit
def test_slot_dict_shape_contains_required_keys() -> None:
    row = _row("lexical.vocabulary_richness", value_kind=ValueKind.NUMERIC, value_numeric=0.72)
    result = observation_to_slot(row)
    assert result is not None
    slot = result.slot_dict
    assert "value" in slot
    assert "last_observation_id" in slot
    assert "derived_from_observation_count" in slot


@pytest.mark.unit
def test_slot_dict_value_prefers_numeric() -> None:
    row = _row("lexical.vocabulary_richness", value_kind=ValueKind.NUMERIC, value_numeric=0.72)
    result = observation_to_slot(row)
    assert result is not None
    assert result.slot_dict["value"] == 0.72


@pytest.mark.unit
def test_slot_dict_value_uses_hash() -> None:
    row = _row(
        "stylometric.function_word_distribution_top50",
        value_kind=ValueKind.HASH,
        value_hash="aabbccdd",
    )
    result = observation_to_slot(row)
    assert result is not None
    assert result.slot_dict["value"] == "aabbccdd"


@pytest.mark.unit
def test_slot_dict_last_observation_id_is_row_id() -> None:
    row = _row("lexical.vocabulary_richness", value_kind=ValueKind.NUMERIC, value_numeric=0.5)
    result = observation_to_slot(row)
    assert result is not None
    assert result.slot_dict["last_observation_id"] == str(row.id)


@pytest.mark.unit
def test_function_word_language_es_propagates_to_slot() -> None:
    row = _row(
        "stylometric.function_word_distribution_top50",
        value_kind=ValueKind.HASH,
        value_hash="deadbeef",
    )
    result = observation_to_slot(row, envelope_source="eyenet/sensor/primitives/fnwd-top50:v0.2#es")
    assert result is not None
    assert result.slot_dict["language"] == "es"


@pytest.mark.unit
def test_function_word_language_en_propagates_to_slot() -> None:
    row = _row(
        "stylometric.function_word_distribution_top50",
        value_kind=ValueKind.HASH,
        value_hash="deadbeef",
    )
    result = observation_to_slot(row, envelope_source="eyenet/sensor/primitives/fnwd-top50:v0.2#en")
    assert result is not None
    assert result.slot_dict["language"] == "en"


@pytest.mark.unit
def test_function_word_missing_envelope_source_omits_language() -> None:
    row = _row(
        "stylometric.function_word_distribution_top50",
        value_kind=ValueKind.HASH,
        value_hash="deadbeef",
    )
    result = observation_to_slot(row)  # no envelope_source
    assert result is not None
    assert "language" not in result.slot_dict


@pytest.mark.unit
def test_function_word_invalid_lang_suffix_omits_language() -> None:
    row = _row(
        "stylometric.function_word_distribution_top50",
        value_kind=ValueKind.HASH,
        value_hash="deadbeef",
    )
    # Suffix is not in the recognised set — must not be smuggled into the slot.
    result = observation_to_slot(row, envelope_source="eyenet/sensor/primitives/fnwd-top50:v0.2#zz")
    assert result is not None
    assert "language" not in result.slot_dict


@pytest.mark.unit
def test_char_ngram_does_not_pick_up_language_from_suffix() -> None:
    """Only whitelisted primitives consume the #lang suffix. char_ngram does not."""
    row = _row(
        "stylometric.character_ngram_simhash",
        value_kind=ValueKind.HASH,
        value_hash="deadbeef",
    )
    result = observation_to_slot(row, envelope_source="eyenet/sensor/primitives/char3gram:v0.2#es")
    assert result is not None
    assert "language" not in result.slot_dict
