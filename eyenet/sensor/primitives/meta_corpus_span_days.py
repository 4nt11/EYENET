"""Meta primitive: corpus_span_days.

Wall-clock duration in fractional days between the actor's earliest and
latest message. First-to-last only — blind to silence in between. Pair
with `meta.active_days` / `meta.activity_density` for presence shape.
See BEHAVE-TEXT 0.1.2 `primitives.py` lines 123-130.
"""

from __future__ import annotations

import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

from ._meta_kernel import CONFIDENCE_HEURISTIC_TAG, CONFIDENCE_NUMERIC, compute_meta_stats

PRIMITIVE_NAME: str = "meta.corpus_span_days"
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
        value=stats.corpus_span_days,
        confidence=CONFIDENCE_NUMERIC[stats.fingerprint_confidence],
        window=Window(start_ts=stats.window_start_ts, end_ts=stats.window_end_ts),
        source=f"eyenet/sensor/primitives/meta-corpus-span-days:v{PRIMITIVE_VERSION}#{CONFIDENCE_HEURISTIC_TAG}",
        evidence_ref=None,
        ts=time.time(),
    )


__all__ = ["PRIMITIVE_NAME", "PRIMITIVE_VERSION", "compute"]
