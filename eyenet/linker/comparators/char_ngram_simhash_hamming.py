"""Comparator: character_ngram_simhash → Hamming on 64-bit simhash.

Threshold: default 10 bits (looser than function_word; char n-grams are
noisier) — language-blind fallback retained from M4. The Rutify grid
(M5, 2026-05-23) found AUC=0.68 on short Spanish chat with max
achievable precision 0.33; Spanish is explicitly DISABLED at the config
layer (``LinkerThresholds`` ships ``char_ngram_simhash_hamming_per_lang =
{"es": None}``). The 10-bit default remains uncalibrated for non-Spanish
languages.

Slot path: ``stylometric_summary.char_ngram_simhash``.
"""

from __future__ import annotations

from eyenet.contracts.attribution import ProfileCurrentEnvelope

from ._base import ComparisonResult, read_function_word_language
from ._distance import hamming64

_DEFAULT_THRESHOLD = 10


class _CharNgramSimhashHamming:
    name: str = "char_ngram_simhash_hamming"
    version: str = "0.1"
    slot_path: str = "stylometric_summary.char_ngram_simhash"
    primitive_name: str = "character_ngram_simhash"
    default_threshold: int = _DEFAULT_THRESHOLD

    def slot_value(self, envelope: ProfileCurrentEnvelope) -> str | None:
        slot = envelope.stylometric_summary.get("char_ngram_simhash")
        if not isinstance(slot, dict):
            return None
        v = slot.get("value")
        return str(v) if v is not None else None

    def slot_language(self, envelope: ProfileCurrentEnvelope) -> str | None:
        # char_ngram primitive does not detect language itself. Inherit from
        # the function_word slot — the actor-wide language tag.
        return read_function_word_language(envelope)

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


CharNgramSimhashHamming = _CharNgramSimhashHamming()

__all__ = ["CharNgramSimhashHamming"]
