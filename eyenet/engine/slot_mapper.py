"""Slot mapper — maps an ObservationRow to a Profile summary block + slot.

Returns `(block_name, slot_key, slot_value_dict)` or `None` if the primitive
has no Profile mapping. Unknown primitives return `None` (soft-ignore).

Slot mapping is locked in PLAN.md §M2 (four M2 primitives) and §M3 (four new
primitives). Adding a new primitive = add one entry to `_SLOT_MAP`.

Per PLAN §4 / attribution.py `ProfileSummaryBlock` docstring: every slot dict
carries `{"value": ..., "last_observation_id": ..., "derived_from_observation_count": ...}`.
The `last_observation_id` and count are injected here so the caller only deals
with the triple `(block_name, slot_key, slot_dict)`.

M5: optional ``envelope_source`` parameter lets the caller surface metadata
encoded in the wire ``Observation.source`` field (e.g. detected language from
``function_word_distribution_top50``, which writes ``…#es`` or ``…#en``).
When recognised, the suffix is parsed and written to the slot dict (e.g.
``language="es"``). This drives per-language threshold lookup in the Linker
without requiring a schema migration on ``ObservationRow``.
"""

from __future__ import annotations

from typing import NamedTuple

from eyenet.contracts.observation import ObservationRow

# Primitives whose wire ``Observation.source`` ends with ``#<lang>`` and whose
# detected language is meaningful at the profile-slot level (used by the
# Linker for per-language threshold resolution).
_LANGUAGE_SUFFIX_PRIMITIVES: frozenset[str] = frozenset(
    {
        "stylometric.function_word_distribution_top50",
        # M6.5 spaCy trio — both simhash primitives append #<lang> so the
        # Linker can resolve per-language thresholds.
        "stylometric.pos_ngram_signature",
        "lexical.optional_grammar_signature",
    }
)
_VALID_LANGUAGE_CODES: frozenset[str] = frozenset({"en", "es"})

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
    # M6 — locale-aware primitives
    "lexical.dialect_region": (
        "lexical_summary",
        "dialect_region",
    ),
    # M6.5 — spaCy trio (locale-aware morpho-syntactic primitives)
    "stylometric.pos_ngram_signature": (
        "stylometric_summary",
        "pos_ngram_signature",
    ),
    "lexical.evaluative_morphology_density": (
        "lexical_summary",
        "evaluative_morphology_density",
    ),
    "lexical.optional_grammar_signature": (
        "lexical_summary",
        "optional_grammar_signature",
    ),
    # M5.5 — meta.* (BEHAVE-TEXT 0.1.2). All route to temporal_summary.
    # Slot key for meta.total_messages is intentionally "message_count"
    # (not "total_messages") to match chatty_member.REQUIRED_SLOTS, which
    # was calibrated against that key in M5 before the primitive landed.
    "meta.total_messages": (
        "temporal_summary",
        "message_count",
    ),
    "meta.corpus_span_days": (
        "temporal_summary",
        "corpus_span_days",
    ),
    "meta.msg_per_day": (
        "temporal_summary",
        "msg_per_day",
    ),
    "meta.active_days": (
        "temporal_summary",
        "active_days",
    ),
    "meta.activity_density": (
        "temporal_summary",
        "activity_density",
    ),
    "meta.first_seen_ts": (
        "temporal_summary",
        "first_seen_ts",
    ),
    "meta.last_seen_ts": (
        "temporal_summary",
        "last_seen_ts",
    ),
    "meta.fingerprint_confidence": (
        "temporal_summary",
        "fingerprint_confidence",
    ),
}


class SlotMapping(NamedTuple):
    block_name: str
    slot_key: str
    slot_dict: dict[str, object]


def _parse_language_suffix(source: str) -> str | None:
    """Extract a recognised ``#<lang>`` suffix from a wire ``Observation.source``.

    Returns the language code (``"en"`` / ``"es"``) when present and valid,
    otherwise ``None``. The validity check is intentional: it shields the
    profile slot from absorbing arbitrary suffixes if a future primitive
    overloads ``#`` for unrelated purposes.
    """
    _, sep, tail = source.rpartition("#")
    if not sep:
        return None
    code = tail.strip().lower()
    return code if code in _VALID_LANGUAGE_CODES else None


def observation_to_slot(
    obs_row: ObservationRow,
    *,
    envelope_source: str | None = None,
) -> SlotMapping | None:
    """Map an ObservationRow to a (block_name, slot_key, slot_dict) triple.

    Returns None if the primitive is not mapped to any Profile slot.

    The `slot_dict` shape is the per-slot convention documented in
    `ProfileSummaryBlock`:
        {"value": ..., "last_observation_id": ..., "derived_from_observation_count": ...}

    When ``envelope_source`` is provided and the primitive is in
    ``_LANGUAGE_SUFFIX_PRIMITIVES``, a ``language`` field is added to
    ``slot_dict`` (M5 — drives per-language threshold lookup in the Linker).
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

    if envelope_source and obs_row.primitive_name in _LANGUAGE_SUFFIX_PRIMITIVES:
        lang = _parse_language_suffix(envelope_source)
        if lang is not None:
            slot_dict["language"] = lang

    return SlotMapping(block_name=block_name, slot_key=slot_key, slot_dict=slot_dict)


__all__ = ["SlotMapping", "observation_to_slot"]
