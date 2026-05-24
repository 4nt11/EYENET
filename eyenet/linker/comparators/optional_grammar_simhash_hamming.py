"""Comparator: ``optional_grammar_signature`` → Hamming on 64-bit simhash.

Stable per-author preference at Spanish grammar choice points (compound
past, subjunctive use rate, leísmo/laísmo/loísmo, relative pronoun
choice). The 12-bit default is looser than POS bigrams because the
choice-point feature space is sparser (~10 buckets) and within-author
drift is higher.

Spanish is explicitly DISABLED at the config layer per the M6.5 Rutify
calibration (2026-05-23): AUC=0.6319 with max precision 0.080 at any
threshold — same reason as the sibling simhash comparators.
``LinkerThresholds`` ships ``optional_grammar_simhash_hamming_per_lang =
{"es": None}``. The 12-bit default remains uncalibrated for non-Spanish
languages until a corpus lands.

Slot path: ``lexical_summary.optional_grammar_signature``. Source label
carries the primitive's own language detection (``#es``), so
``slot_language`` reads the slot dict directly.
"""

from __future__ import annotations

from eyenet.contracts.attribution import ProfileCurrentEnvelope

from ._base import ComparisonResult
from ._distance import hamming64

_DEFAULT_THRESHOLD = 12


class _OptionalGrammarSimhashHamming:
    name: str = "optional_grammar_simhash_hamming"
    version: str = "0.1"
    slot_path: str = "lexical_summary.optional_grammar_signature"
    primitive_name: str = "optional_grammar_signature"
    default_threshold: int = _DEFAULT_THRESHOLD

    def slot_value(self, envelope: ProfileCurrentEnvelope) -> str | None:
        slot = envelope.lexical_summary.get("optional_grammar_signature")
        if not isinstance(slot, dict):
            return None
        v = slot.get("value")
        return str(v) if v is not None else None

    def slot_language(self, envelope: ProfileCurrentEnvelope) -> str | None:
        slot = envelope.lexical_summary.get("optional_grammar_signature")
        if not isinstance(slot, dict):
            return None
        lang = slot.get("language")
        return lang if isinstance(lang, str) else None

    def compare(self, value_a: str, value_b: str, threshold: int) -> ComparisonResult:
        dist = hamming64(value_a, value_b)
        within = dist <= threshold
        score = max(0.0, 1.0 - dist / threshold) if threshold > 0 else (1.0 if dist == 0 else 0.0)
        return ComparisonResult(
            method=self.name,
            distance=dist,
            score=round(score, 4),
            within_threshold=within,
            evidence={"hex_a": value_a, "hex_b": value_b, "threshold": threshold},
        )


OptionalGrammarSimhashHamming = _OptionalGrammarSimhashHamming()

__all__ = ["OptionalGrammarSimhashHamming"]
