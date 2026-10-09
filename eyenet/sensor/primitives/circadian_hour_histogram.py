"""Circadian primitive: hour_histogram (BEHAVE-TEXT 0.1.4).

24-bin normalized activity histogram by UTC hour. THE timezone signal the
EYENET engine cross-correlates against candidate offsets. Degrades under
low-precision timestamps (day-granular dates pile into bin 0); dow_histogram
is the robust fallback.
"""

from __future__ import annotations

import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

from ._meta_kernel import CONFIDENCE_HEURISTIC_TAG, CONFIDENCE_NUMERIC, compute_meta_stats

PRIMITIVE_NAME: str = "circadian.hour_histogram"
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
        value=list(stats.hour_histogram),
        confidence=CONFIDENCE_NUMERIC[stats.fingerprint_confidence],
        window=Window(start_ts=stats.window_start_ts, end_ts=stats.window_end_ts),
        source=f"eyenet/sensor/primitives/circadian-hour-histogram:v{PRIMITIVE_VERSION}#{CONFIDENCE_HEURISTIC_TAG}",
        evidence_ref=None,
        ts=time.time(),
    )


__all__ = ["PRIMITIVE_NAME", "PRIMITIVE_VERSION", "compute"]
