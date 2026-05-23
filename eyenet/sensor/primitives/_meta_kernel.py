"""Shared kernel for the meta.* primitives (BEHAVE-TEXT 0.1.2).

The eight meta primitives are all derivable from a single pass over the
per-actor corpus timestamps. This module computes them once and exposes a
frozen `MetaStats` dataclass; each `meta_*.py` primitive then wraps the
relevant field in an `Observation`.

Confidence cutoffs (`meta.fingerprint_confidence`) are EXTRACTOR-DEFINED
per the BEHAVE-TEXT 0.1.2 spec (`primitives.py` lines 164-174 — the registry
declares the semantic contract, not the formula). EYENET's v1 heuristic:

    high   : total_messages >= 100 AND active_days >= 7
    medium : total_messages >= 30  AND active_days >= 2
    low    : otherwise

The source label suffix `#confidence-v1` pins this heuristic version so
downstream consumers can detect drift if the cutoffs are tuned later.

Edge cases (per spec notes):
* Empty corpus -> `None`; no Observation emitted for any meta primitive.
* `corpus_span_days == 0.0` (single-day actor) -> `msg_per_day` and
  `activity_density` are returned as `None` (spec: "Undefined when
  corpus_span_days = 0; extractors should emit null/omit"). The remaining
  six primitives still emit normally.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

CONFIDENCE_HEURISTIC_TAG: str = "confidence-v1"

_HIGH_MIN_MESSAGES: int = 100
_HIGH_MIN_ACTIVE_DAYS: int = 7
_MEDIUM_MIN_MESSAGES: int = 30
_MEDIUM_MIN_ACTIVE_DAYS: int = 2

_SECONDS_PER_DAY: float = 86400.0


@dataclass(frozen=True)
class MetaStats:
    """Derived corpus-level statistics for a single actor.

    Fields map 1:1 onto the eight `meta.*` BEHAVE-TEXT primitives.
    `msg_per_day` and `activity_density` are `None` when `corpus_span_days`
    is 0.0 (single-day actor), per the BEHAVE-TEXT 0.1.2 spec contract.
    """

    total_messages: int
    corpus_span_days: float
    msg_per_day: float | None
    active_days: int
    activity_density: float | None
    first_seen_ts: str
    last_seen_ts: str
    fingerprint_confidence: str
    # Underlying span in seconds, surfaced for `Window` construction on each
    # primitive Observation (avoids re-parsing the ISO strings).
    window_start_ts: float
    window_end_ts: float


def compute_meta_stats(
    corpus: list[tuple[datetime, UUID, str]],
) -> MetaStats | None:
    """Compute all eight meta.* values from per-actor corpus timestamps.

    Returns `None` when the corpus is empty (no Observation should be
    emitted for any meta primitive in that case).
    """
    if not corpus:
        return None

    timestamps: list[datetime] = [ts for ts, _, _ in corpus]
    if any(ts.tzinfo is None for ts in timestamps):
        raise ValueError(
            "compute_meta_stats requires timezone-aware datetimes; "
            "naive datetimes cannot be bucketed to UTC calendar days"
        )

    total_messages = len(timestamps)
    first_ts = min(timestamps)
    last_ts = max(timestamps)

    span_seconds = (last_ts - first_ts).total_seconds()
    corpus_span_days = span_seconds / _SECONDS_PER_DAY

    active_days_set: set[tuple[int, int, int]] = set()
    for ts in timestamps:
        utc = ts.astimezone(UTC)
        active_days_set.add((utc.year, utc.month, utc.day))
    active_days = len(active_days_set)

    msg_per_day: float | None
    activity_density: float | None
    if corpus_span_days > 0.0:
        msg_per_day = total_messages / corpus_span_days
        activity_density = min(1.0, active_days / corpus_span_days)
    else:
        msg_per_day = None
        activity_density = None

    fingerprint_confidence = _classify_confidence(
        total_messages=total_messages,
        active_days=active_days,
    )

    return MetaStats(
        total_messages=total_messages,
        corpus_span_days=corpus_span_days,
        msg_per_day=msg_per_day,
        active_days=active_days,
        activity_density=activity_density,
        first_seen_ts=first_ts.astimezone(UTC).isoformat(),
        last_seen_ts=last_ts.astimezone(UTC).isoformat(),
        fingerprint_confidence=fingerprint_confidence,
        window_start_ts=first_ts.timestamp(),
        window_end_ts=last_ts.timestamp(),
    )


def _classify_confidence(*, total_messages: int, active_days: int) -> str:
    if total_messages >= _HIGH_MIN_MESSAGES and active_days >= _HIGH_MIN_ACTIVE_DAYS:
        return "high"
    if total_messages >= _MEDIUM_MIN_MESSAGES and active_days >= _MEDIUM_MIN_ACTIVE_DAYS:
        return "medium"
    return "low"


CONFIDENCE_NUMERIC: dict[str, float] = {"low": 0.3, "medium": 0.6, "high": 0.9}
"""Mapping from categorical fingerprint_confidence to the numeric
Observation.confidence field. Uniform with other primitives that compute
confidence from a token-count ratio."""


__all__ = [
    "CONFIDENCE_HEURISTIC_TAG",
    "CONFIDENCE_NUMERIC",
    "MetaStats",
    "compute_meta_stats",
]
