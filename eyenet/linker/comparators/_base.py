"""Comparator Protocol — every linker comparator implements this interface.

A comparator extracts a value from a profile slot, computes a distance metric,
and returns a ComparisonResult. The registry runs all eligible comparators on
every incoming ProfileCurrent; the Linker emits a LinkageProposed for each
match below threshold.

`slot_path`: dot-path into ProfileCurrentEnvelope
(e.g. "stylometric_summary.function_word_simhash").
`primitive_name`: key used in the VectorIndex (must match the BEHAVE-TEXT primitive name).
`default_threshold`: default max Hamming distance; operator-overridable via config.
`slot_language(envelope)`: optional per-envelope language code that the Linker
uses to look up a per-language threshold override (PLAN §M5). Comparators that
do not condition on language return ``None``; the Linker then uses
``default_threshold``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from eyenet.contracts.attribution import ProfileCurrentEnvelope


@dataclass(frozen=True)
class ComparisonResult:
    """Result of one comparator's evaluation of two profile slot values."""

    method: str
    distance: int
    score: float  # 1.0 - (distance / threshold), clamped to [0.0, 1.0]
    within_threshold: bool
    evidence: dict[str, object] = field(default_factory=dict)


class Comparator(Protocol):
    name: str
    version: str
    slot_path: str
    primitive_name: str
    default_threshold: int

    def slot_value(self, envelope: ProfileCurrentEnvelope) -> str | None:
        """Extract the raw slot value (hex string for simhashes) from an envelope.

        Returns None if the slot is absent or empty — the Linker will skip this
        comparator for this envelope rather than raising.
        """
        ...

    def slot_language(self, envelope: ProfileCurrentEnvelope) -> str | None:
        """Return the language code (ISO 639-1) for this slot, if any.

        Used by the Linker to look up a per-language threshold override
        (``LinkerThresholds.<name>_per_lang[code]``). Returns ``None`` when
        the comparator does not condition on language OR the language is
        unknown for this envelope; the Linker then falls back to
        ``default_threshold``.
        """
        ...

    def compare(
        self,
        value_a: str,
        value_b: str,
        threshold: int,
    ) -> ComparisonResult:
        """Compute distance between two slot values.

        Args:
            value_a: slot value for actor A
            value_b: slot value for actor B
            threshold: max distance for a match (from LinkerConfig or default)
        """
        ...


def read_function_word_language(envelope: ProfileCurrentEnvelope) -> str | None:
    """Shared helper: read ``stylometric_summary.function_word_simhash.language``.

    Multiple comparators (e.g. ``char_ngram_simhash_hamming``) want to apply
    per-language thresholds even when their own primitive does not detect
    language. They look at the function-word slot — which is always written
    first per profile — for the actor-wide language signal.
    """
    slot = envelope.stylometric_summary.get("function_word_simhash")
    if not isinstance(slot, dict):
        return None
    lang = slot.get("language")
    return lang if isinstance(lang, str) else None


__all__ = ["Comparator", "ComparisonResult", "read_function_word_language"]
