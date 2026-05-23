"""Meta primitive: activity_density.

active_days / corpus_span_days. Single scalar capturing 'how filled is
the span?'. 1.0 = present every day of the window. Spec note: undefined
when corpus_span_days = 0; this extractor returns `None` in that case,
suppressing the Observation entirely.

See BEHAVE-TEXT 0.1.2 `primitives.py` lines 147-153.
"""

from __future__ import annotations

import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

from ._meta_kernel import CONFIDENCE_HEURISTIC_TAG, CONFIDENCE_NUMERIC, compute_meta_stats

PRIMITIVE_NAME: str = "meta.activity_density"
PRIMITIVE_VERSION: str = "0.1"


def compute(
    *,
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],  # noqa: ARG001
) -> Observation | None:
    stats = compute_meta_stats(corpus)
    if stats is None or stats.activity_density is None:
        return None

    return Observation(
        primitive=PRIMITIVE_NAME,
        value=stats.activity_density,
        confidence=CONFIDENCE_NUMERIC[stats.fingerprint_confidence],
        window=Window(start_ts=stats.window_start_ts, end_ts=stats.window_end_ts),
        source=f"eyenet/sensor/primitives/meta-activity-density:v{PRIMITIVE_VERSION}#{CONFIDENCE_HEURISTIC_TAG}",
        evidence_ref=None,
        ts=time.time(),
    )


__all__ = ["PRIMITIVE_NAME", "PRIMITIVE_VERSION", "compute"]
