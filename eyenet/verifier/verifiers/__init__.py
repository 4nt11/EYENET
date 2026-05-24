"""Verifier registry — REGISTRY is the ordered tuple of active verifiers.

Mirrors ``eyenet.linker.comparators.__init__``. New verifiers register here
without touching the Verifier service.
"""

from __future__ import annotations

from ._base import VerificationResult, Verifier
from .compression_distance import CompressionDistance
from .general_impostors import GeneralImpostors


def default_registry(impostor_corpora: list[list[str]] | None = None) -> tuple[Verifier, ...]:
    """Construct the default verifier REGISTRY.

    The Verifier service holds one instance of each. GI takes an impostor
    pool at construction time — passed in by the service after loading
    the pool fixture. Empty pool ⇒ GI degrades to plain cosine with low
    confidence (see GeneralImpostors._plain_cosine).
    """
    return (
        GeneralImpostors(impostor_corpora=impostor_corpora or []),
        CompressionDistance(),
    )


REGISTRY: tuple[Verifier, ...] = default_registry()


__all__ = [
    "REGISTRY",
    "CompressionDistance",
    "GeneralImpostors",
    "VerificationResult",
    "Verifier",
    "default_registry",
]
