"""Verifier Protocol — every M8 verifier implements this interface.

A verifier takes two per-actor message corpora (chronological lists of
body strings) and a language hint, and returns a `VerificationResult`
with a score in `[0.0, 1.0]` where higher = more likely SAME author.

Mirrors `eyenet.linker.comparators._base.Comparator`, but on bodies, not
on profile slot hashes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class VerificationResult:
    """One verifier's evaluation of a candidate pair."""

    method: str
    score: float  # 0.0 = clearly different, 1.0 = clearly same; calibrated per method
    confidence: float  # 0.0 = unusable (e.g. corpus too short), 1.0 = full signal
    evidence: dict[str, object] = field(default_factory=dict)
    skipped: bool = False
    skip_reason: str | None = None


class Verifier(Protocol):
    """Verifier contract — see module docstring."""

    name: str
    version: str
    requires_language: bool
    """If True, ``language`` must be a non-None BCP-47 code or the verifier skips."""

    min_messages_per_actor: int
    """If either actor's corpus has fewer messages, the verifier skips."""

    def verify(
        self,
        corpus_a: list[str],
        corpus_b: list[str],
        *,
        language: str | None,
    ) -> VerificationResult:
        """Compute the verifier's similarity score for the pair.

        Implementations MUST be deterministic given identical inputs OR
        carry a RNG seed in their constructor — calibration depends on
        reproducibility. They MUST return a `VerificationResult` (never
        raise on insufficient data; use `skipped=True` + `skip_reason`).
        """
        ...


__all__ = ["VerificationResult", "Verifier"]
