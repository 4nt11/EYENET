"""Stylometric primitives: message_length_class + message_length_variance_class.

Two primitives, one file — they share the same corpus pass.

`stylometric.message_length_class` (BEHAVE-TEXT spec):
    Median message word-count bucket over the corpus window.
    Values: "short" (1-5 words) | "medium" (6-20) | "long" (21-50) | "paragraph" (>50)

`stylometric.message_length_variance_class` (BEHAVE-TEXT spec):
    Coefficient of variation (std/mean) of per-message word counts.
    Values: "tight" (CV<0.5) | "varied" (0.5<=CV<1.5) | "bimodal" (CV>=1.5)

The variance class is the actual bot discriminator: bots emit messages of
nearly constant length (CV≈0 → "tight"); humans vary widely.
"""

from __future__ import annotations

import statistics
import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

PRIMITIVE_NAME_CLASS = "stylometric.message_length_class"
PRIMITIVE_NAME_VARIANCE = "stylometric.message_length_variance_class"
PRIMITIVE_VERSION = "0.1"

MIN_MESSAGES = 5

_SHORT_MAX = 5
_MEDIUM_MAX = 20
_LONG_MAX = 50
_CV_TIGHT_MAX = 0.5
_CV_VARIED_MAX = 1.5


def _word_count(text: str) -> int:
    return len(text.split())


def _bucket_class(median_words: float) -> str:
    if median_words <= _SHORT_MAX:
        return "short"
    if median_words <= _MEDIUM_MAX:
        return "medium"
    if median_words <= _LONG_MAX:
        return "long"
    return "paragraph"


def _bucket_variance(cv: float) -> str:
    if cv < _CV_TIGHT_MAX:
        return "tight"
    if cv < _CV_VARIED_MAX:
        return "varied"
    return "bimodal"


def _compute_both(
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],
) -> tuple[str | None, str | None]:
    word_counts = [_word_count(bodies[ref]) for _, _, ref in corpus if ref in bodies]
    if len(word_counts) < MIN_MESSAGES:
        return None, None
    median = statistics.median(word_counts)
    mean = statistics.mean(word_counts)
    if mean == 0:
        return _bucket_class(median), "tight"
    std = statistics.stdev(word_counts) if len(word_counts) > 1 else 0.0
    cv = std / mean
    return _bucket_class(median), _bucket_variance(cv)


def compute_class(
    *,
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],
) -> Observation | None:
    cls, _ = _compute_both(corpus, bodies)
    if cls is None:
        return None
    ts_vals = [ts.timestamp() for ts, _, _ in corpus]
    return Observation(
        primitive=PRIMITIVE_NAME_CLASS,
        value=cls,
        confidence=min(1.0, len(corpus) / 50),
        window=Window(start_ts=min(ts_vals), end_ts=max(ts_vals)),
        source=f"eyenet/sensor/primitives/message_length:v{PRIMITIVE_VERSION}",
        evidence_ref=corpus[-1][2] if corpus else None,
        ts=time.time(),
    )


def compute_variance(
    *,
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],
) -> Observation | None:
    _, var = _compute_both(corpus, bodies)
    if var is None:
        return None
    ts_vals = [ts.timestamp() for ts, _, _ in corpus]
    return Observation(
        primitive=PRIMITIVE_NAME_VARIANCE,
        value=var,
        confidence=min(1.0, len(corpus) / 50),
        window=Window(start_ts=min(ts_vals), end_ts=max(ts_vals)),
        source=f"eyenet/sensor/primitives/message_length_variance:v{PRIMITIVE_VERSION}",
        evidence_ref=corpus[-1][2] if corpus else None,
        ts=time.time(),
    )


__all__ = [
    "MIN_MESSAGES",
    "PRIMITIVE_NAME_CLASS",
    "PRIMITIVE_NAME_VARIANCE",
    "PRIMITIVE_VERSION",
    "compute_class",
    "compute_variance",
]
