"""Slot mapper — maps an ObservationRow to a Profile summary block + slot.

Returns `(block_name, slot_key, slot_value_dict)` or `None` if the primitive
has no Profile mapping. Unknown primitives return `None` (soft-ignore).

Slot mapping is locked in PLAN.md §M2 (four M2 primitives) and §M3 (four new
primitives). Adding a new primitive = add one entry to `_SLOT_MAP`.

Per PLAN §4 / attribution.py `ProfileSummaryBlock` docstring: every slot dict
carries `{"value": ..., "last_observation_id": ..., "derived_from_observation_count": ...}`.
The `last_observation_id` and count are injected here so the caller only deals
with the triple `(block_name, slot_key, slot_dict)`.
"""

from __future__ import annotations

from typing import NamedTuple

from eyenet.contracts.observation import ObservationRow

# (block_name, slot_key) by primitive_name.
_SLOT_MAP: dict[str, tuple[str, str]] = {
    # M2 primitives (PLAN §M2 primitive → Profile slot mapping table)
    "stylometric.function_word_distribution_top50": (
        "stylometric_summary",
        "function_word_simhash",
    ),
    "stylometric.character_ngram_simhash": (
        "stylometric_summary",
        "char_ngram_simhash",
    ),
    "stylometric.distinctive_vocabulary_signature": (
        "lexical_summary",
        "distinctive_vocab",
    ),
    "lexical.vocabulary_richness": (
        "lexical_summary",
        "mattr",
    ),
    # M3 primitives
    "stylometric.message_length_class": (
        "stylometric_summary",
        "message_length_class",
    ),
    "stylometric.message_length_variance_class": (
        "stylometric_summary",
        "message_length_variance_class",
    ),
    "stylometric.punctuation_style": (
        "stylometric_summary",
        "punctuation_style",
    ),
    "stylometric.typo_signature": (
        "stylometric_summary",
        "typo_signature",
    ),
    "interaction.conversation_initiation_rate": (
        "interaction_summary",
        "conversation_initiation_rate",
    ),
}


class SlotMapping(NamedTuple):
    block_name: str
    slot_key: str
    slot_dict: dict[str, object]


def observation_to_slot(obs_row: ObservationRow) -> SlotMapping | None:
    """Map an ObservationRow to a (block_name, slot_key, slot_dict) triple.

    Returns None if the primitive is not mapped to any Profile slot.

    The `slot_dict` shape is the per-slot convention documented in
    `ProfileSummaryBlock`:
        {"value": ..., "last_observation_id": ..., "derived_from_observation_count": ...}
    """
    entry = _SLOT_MAP.get(obs_row.primitive_name)
    if entry is None:
        return None

    block_name, slot_key = entry

    raw_value: object = (
        obs_row.value_hash
        or obs_row.value_numeric
        or obs_row.value_enum
        or obs_row.value_array
        or obs_row.value_array_numeric
    )

    slot_dict: dict[str, object] = {
        "value": raw_value,
        "last_observation_id": str(obs_row.id),
        "derived_from_observation_count": 0,  # engine increments this per actor
    }

    return SlotMapping(block_name=block_name, slot_key=slot_key, slot_dict=slot_dict)


__all__ = ["SlotMapping", "observation_to_slot"]
