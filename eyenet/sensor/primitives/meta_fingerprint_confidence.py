"""Meta primitive: fingerprint_confidence.

Qualitative reliability rating ('low' / 'medium' / 'high') for this
actor's full fingerprint. Per BEHAVE-TEXT 0.1.2 spec (`primitives.py`
lines 164-174), derivation is EXTRACTOR-DEFINED; this extractor's
heuristic is documented in `_meta_kernel.CONFIDENCE_HEURISTIC_TAG`
(currently 'confidence-v1').

Engines should weight other observations from the same actor
proportionally to this value before compositing — that's the contract.
"""

from __future__ import annotations

import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

from ._meta_kernel import CONFIDENCE_HEURISTIC_TAG, CONFIDENCE_NUMERIC, compute_meta_stats

PRIMITIVE_NAME: str = "meta.fingerprint_confidence"
PRIMITIVE_VERSION: str = "0.1"


def compute(
    *,
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],  # noqa: ARG001
) -> Observation | None:
    stats = compute_meta_stats(corpus)
    if stats is None:
        return None

    return Observation(
        primitive=PRIMITIVE_NAME,
        value=stats.fingerprint_confidence,
        confidence=CONFIDENCE_NUMERIC[stats.fingerprint_confidence],
        window=Window(start_ts=stats.window_start_ts, end_ts=stats.window_end_ts),
        source=f"eyenet/sensor/primitives/meta-fingerprint-confidence:v{PRIMITIVE_VERSION}#{CONFIDENCE_HEURISTIC_TAG}",
        evidence_ref=None,
        ts=time.time(),
    )


__all__ = ["PRIMITIVE_NAME", "PRIMITIVE_VERSION", "compute"]
