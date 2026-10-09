"""Circadian primitive: quiet_span_utc (BEHAVE-TEXT 0.1.4).

``[start_hour, end_hour)`` of the actor's longest low-activity run in UTC
(integer-hour grid). The sleep-gap anchor EYENET maps to a candidate offset.
Gated to >=30 messages AND >=2 active days (the kernel returns None below that);
wrap-around is legal (start > end crosses midnight).
"""

from __future__ import annotations

import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

from ._meta_kernel import CONFIDENCE_HEURISTIC_TAG, CONFIDENCE_NUMERIC, compute_meta_stats

PRIMITIVE_NAME: str = "circadian.quiet_span_utc"
PRIMITIVE_VERSION: str = "0.1"


def compute(
    *,
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],  # noqa: ARG001
) -> Observation | None:
    stats = compute_meta_stats(corpus)
    if stats is None or stats.quiet_span_utc is None:
        return None

    start, end = stats.quiet_span_utc
    return Observation(
        primitive=PRIMITIVE_NAME,
        value=[start, end],
        confidence=CONFIDENCE_NUMERIC[stats.fingerprint_confidence],
        window=Window(start_ts=stats.window_start_ts, end_ts=stats.window_end_ts),
        source=f"eyenet/sensor/primitives/circadian-quiet-span:v{PRIMITIVE_VERSION}#{CONFIDENCE_HEURISTIC_TAG}",
        evidence_ref=None,
        ts=time.time(),
    )


__all__ = ["PRIMITIVE_NAME", "PRIMITIVE_VERSION", "compute"]
