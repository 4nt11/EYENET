"""Normalized Compression Distance (NCD) verifier.

NCD(x, y) = (C(xy) - min(C(x), C(y))) / max(C(x), C(y))

where C() is the compressed-byte-length of a serialized stream. Lower
NCD => more similar. Score reported as ``1.0 - NCD`` clamped to [0, 1].

Language-agnostic, stdlib-only, ~50 LOC. Sidesteps the function-word
domain limit that left M5's simhashes structurally weak for Spanish chat.
"""

from __future__ import annotations

import zlib

from ._base import VerificationResult

# Hard cap on the per-actor concatenated text length. NCD's signal does
# not improve beyond a few tens of KB on chat; the cap bounds zlib cost
# and protects against runaway chatty actors. Symmetric for A and B
# (NCD validity requires comparable input sizes).
_TEXT_CAP_BYTES = 50_000


def _compressed_length(payload: bytes) -> int:
    # Level 6 is zlib's default — well-tuned ratio/speed tradeoff;
    # calibration depends on the level being constant across runs.
    return len(zlib.compress(payload, 6))


class CompressionDistance:
    name: str = "compression_distance"
    version: str = "0.1"
    requires_language: bool = False
    min_messages_per_actor: int = 10

    def verify(
        self,
        corpus_a: list[str],
        corpus_b: list[str],
        *,
        language: str | None,  # noqa: ARG002 — required by Verifier Protocol; NCD is language-agnostic
    ) -> VerificationResult:
        if (
            len(corpus_a) < self.min_messages_per_actor
            or len(corpus_b) < self.min_messages_per_actor
        ):
            return VerificationResult(
                method=self.name,
                score=0.0,
                confidence=0.0,
                skipped=True,
                skip_reason="corpus_too_short",
                evidence={
                    "min_messages": self.min_messages_per_actor,
                    "len_a": len(corpus_a),
                    "len_b": len(corpus_b),
                },
            )

        # Newline-join keeps message boundaries visible to the compressor —
        # boundary tokens are part of the stylometric signal.
        text_a = "\n".join(corpus_a).encode("utf-8")[:_TEXT_CAP_BYTES]
        text_b = "\n".join(corpus_b).encode("utf-8")[:_TEXT_CAP_BYTES]
        if not text_a or not text_b:
            return VerificationResult(
                method=self.name,
                score=0.0,
                confidence=0.0,
                skipped=True,
                skip_reason="empty_corpus",
                evidence={"len_a": len(text_a), "len_b": len(text_b)},
            )

        c_a = _compressed_length(text_a)
        c_b = _compressed_length(text_b)
        # Concatenate in a stable order (alphabetic) so NCD is symmetric
        # under input order — required for the (a, b) vs (b, a) invariant.
        if text_a <= text_b:
            c_ab = _compressed_length(text_a + text_b)
        else:
            c_ab = _compressed_length(text_b + text_a)
        denom = max(c_a, c_b)
        if denom == 0:
            return VerificationResult(
                method=self.name,
                score=0.0,
                confidence=0.0,
                skipped=True,
                skip_reason="degenerate_compression",
                evidence={"c_a": c_a, "c_b": c_b, "c_ab": c_ab},
            )
        ncd = (c_ab - min(c_a, c_b)) / denom
        score = max(0.0, min(1.0, 1.0 - ncd))
        return VerificationResult(
            method=self.name,
            score=score,
            confidence=1.0,
            skipped=False,
            skip_reason=None,
            evidence={
                "c_a": c_a,
                "c_b": c_b,
                "c_ab": c_ab,
                "ncd": ncd,
                "bytes_a": len(text_a),
                "bytes_b": len(text_b),
            },
        )


__all__ = ["CompressionDistance"]
