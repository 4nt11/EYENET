"""Meta primitive: first_seen_ts.

ISO 8601 timestamp (UTC) of the actor's earliest message. Anchors
corpus_span_days in absolute time. See BEHAVE-TEXT 0.1.2
`primitives.py` lines 154-159.

Storage note: FREE_STRING values land in `ObservationRow.value_hash`
(via the converter in `eyenet/sensor/stylometric.py`). The column is a
generic TEXT field — the type label is a legacy artifact of the M2
schema. A dedicated `value_string` column may land later.
"""

from __future__ import annotations

import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

from ._meta_kernel import CONFIDENCE_HEURISTIC_TAG, CONFIDENCE_NUMERIC, compute_meta_stats

PRIMITIVE_NAME: str = "meta.first_seen_ts"
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
        value=stats.first_seen_ts,
        confidence=CONFIDENCE_NUMERIC[stats.fingerprint_confidence],
        window=Window(start_ts=stats.window_start_ts, end_ts=stats.window_end_ts),
        source=f"eyenet/sensor/primitives/meta-first-seen-ts:v{PRIMITIVE_VERSION}#{CONFIDENCE_HEURISTIC_TAG}",
        evidence_ref=None,
        ts=time.time(),
    )


__all__ = ["PRIMITIVE_NAME", "PRIMITIVE_VERSION", "compute"]
