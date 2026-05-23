"""Meta primitive: msg_per_day.

total_messages / corpus_span_days. The key rate that separates a bursty
single-session visitor from a long-tail lurker. Spec note: undefined when
corpus_span_days = 0 (single-day actor) — this extractor returns `None`
in that case, which suppresses the Observation entirely.

See BEHAVE-TEXT 0.1.2 `primitives.py` lines 131-138.
"""

from __future__ import annotations

import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

from ._meta_kernel import CONFIDENCE_HEURISTIC_TAG, CONFIDENCE_NUMERIC, compute_meta_stats

PRIMITIVE_NAME: str = "meta.msg_per_day"
PRIMITIVE_VERSION: str = "0.1"


def compute(
    *,
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],  # noqa: ARG001
) -> Observation | None:
    stats = compute_meta_stats(corpus)
    if stats is None or stats.msg_per_day is None:
        return None

    return Observation(
        primitive=PRIMITIVE_NAME,
        value=stats.msg_per_day,
        confidence=CONFIDENCE_NUMERIC[stats.fingerprint_confidence],
        window=Window(start_ts=stats.window_start_ts, end_ts=stats.window_end_ts),
        source=f"eyenet/sensor/primitives/meta-msg-per-day:v{PRIMITIVE_VERSION}#{CONFIDENCE_HEURISTIC_TAG}",
        evidence_ref=None,
        ts=time.time(),
    )


__all__ = ["PRIMITIVE_NAME", "PRIMITIVE_VERSION", "compute"]
