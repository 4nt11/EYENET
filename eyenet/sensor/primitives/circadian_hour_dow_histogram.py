"""Circadian primitive: hour_dow_histogram (BEHAVE-TEXT 0.1.4).

168-bin joint normalized histogram over (day-of-week x UTC hour), index =
dow*24 + hour (dow 0=Monday). The high-resolution signal the two marginals
cannot express ('Saturday 03:00' vs 'Tuesday 03:00'). Emitted separately from
the marginals because this sparse grid degrades faster on thin / low-precision
actors.
"""

from __future__ import annotations

import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

from ._meta_kernel import CONFIDENCE_HEURISTIC_TAG, CONFIDENCE_NUMERIC, compute_meta_stats

PRIMITIVE_NAME: str = "circadian.hour_dow_histogram"
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
        value=list(stats.hour_dow_histogram),
        confidence=CONFIDENCE_NUMERIC[stats.fingerprint_confidence],
        window=Window(start_ts=stats.window_start_ts, end_ts=stats.window_end_ts),
        source=f"eyenet/sensor/primitives/circadian-hour-dow-histogram:v{PRIMITIVE_VERSION}#{CONFIDENCE_HEURISTIC_TAG}",
        evidence_ref=None,
        ts=time.time(),
    )


__all__ = ["PRIMITIVE_NAME", "PRIMITIVE_VERSION", "compute"]
