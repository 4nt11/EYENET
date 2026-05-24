"""Comparator: ``pos_ngram_signature`` → Hamming on 64-bit simhash.

The POS-bigram simhash captures syntactic skeleton independent of
vocabulary. Threshold default of 10 bits is the language-blind
first-principles starting point used when no per-language override
exists.

Spanish is explicitly DISABLED at the config layer per the M6.5 Rutify
calibration (2026-05-23): AUC=0.6108 with max precision 0.200 at any
threshold — the precision-floor:0.70 strategy cannot be satisfied.
``LinkerThresholds`` ships ``pos_ngram_simhash_hamming_per_lang =
{"es": None}``. The 10-bit default remains uncalibrated for non-Spanish
languages until a corpus lands.

Slot path: ``stylometric_summary.pos_ngram_signature``. The primitive
emits ``#<lang>`` in its source label, so ``slot_language`` reads
``language`` directly off the slot dict (no fallback to function-word
needed — this primitive detects language itself).
"""

from __future__ import annotations

from eyenet.contracts.attribution import ProfileCurrentEnvelope

from ._base import ComparisonResult
from ._distance import hamming64

# First-principles default. The M5/M6.5 calibration grid is the source of
# truth for the calibrated per-language values; this is the language-
# blind fallback for codes that have not been calibrated yet.
_DEFAULT_THRESHOLD = 10


class _PosNgramSimhashHamming:
    name: str = "pos_ngram_simhash_hamming"
    version: str = "0.1"
    slot_path: str = "stylometric_summary.pos_ngram_signature"
    primitive_name: str = "pos_ngram_signature"
    default_threshold: int = _DEFAULT_THRESHOLD

    def slot_value(self, envelope: ProfileCurrentEnvelope) -> str | None:
        slot = envelope.stylometric_summary.get("pos_ngram_signature")
        if not isinstance(slot, dict):
            return None
        v = slot.get("value")
        return str(v) if v is not None else None

    def slot_language(self, envelope: ProfileCurrentEnvelope) -> str | None:
        slot = envelope.stylometric_summary.get("pos_ngram_signature")
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


PosNgramSimhashHamming = _PosNgramSimhashHamming()

__all__ = ["PosNgramSimhashHamming"]
