"""Comparator: function_word_distribution_top50 → Hamming on 64-bit simhash.

Threshold: default 8 bits (UNCALIBRATED — tightened by Rutify in M5).
Slot path: stylometric_summary.function_word_simhash
"""

from __future__ import annotations

from eyenet.contracts.attribution import ProfileCurrentEnvelope

from ._base import ComparisonResult
from ._distance import hamming64

# UNCALIBRATED default. Override via config.toml [linker.thresholds].
_DEFAULT_THRESHOLD = 8


class _FunctionWordSimhashHamming:
    name: str = "function_word_simhash_hamming"
    version: str = "0.1"
    slot_path: str = "stylometric_summary.function_word_simhash"
    primitive_name: str = "function_word_distribution_top50"
    default_threshold: int = _DEFAULT_THRESHOLD

    def slot_value(self, envelope: ProfileCurrentEnvelope) -> str | None:
        slot = envelope.stylometric_summary.get("function_word_simhash")
        if not isinstance(slot, dict):
            return None
        v = slot.get("value")
        return str(v) if v is not None else None

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


FunctionWordSimhashHamming = _FunctionWordSimhashHamming()

__all__ = ["FunctionWordSimhashHamming"]
