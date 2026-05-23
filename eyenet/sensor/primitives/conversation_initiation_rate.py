"""Interaction primitive: conversation_initiation_rate.

Ratio of thread-starting messages to total messages in the corpus window.
A "thread-starting" message has `reply_to_msg_id IS NULL` — it begins a new
conversation rather than replying to an existing one.

Value range: 0.0 (always replies) to 1.0 (always initiates new threads).

Interpretation:
  ≈ 0.0  → observer / lurker, rarely initiates
  ≈ 0.5  → normal user, mix of posts and replies
  ≥ 0.95 → bot / broadcast poster, almost never replies

Uses `CorpusStore.iter_since_with_reply` (M3) which returns the reply_to_msg_id
per row. Sensors are stateless across actors; all state lives in the corpus
window read from storage.

Per BEHAVE-TEXT spec: NUMERIC value kind, 0..1.
"""

from __future__ import annotations

import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

PRIMITIVE_NAME = "interaction.conversation_initiation_rate"
PRIMITIVE_VERSION = "0.1"
MIN_MESSAGES = 10


async def compute_async(
    *,
    corpus_with_reply: list[tuple[datetime, UUID, str, UUID | None]],
) -> Observation | None:
    """Async variant — used by the sensor which has the reply-aware corpus."""
    if len(corpus_with_reply) < MIN_MESSAGES:
        return None

    total = len(corpus_with_reply)
    initiations = sum(1 for _, _, _, reply in corpus_with_reply if reply is None)
    rate = initiations / total

    ts_vals = [ts.timestamp() for ts, _, _, _ in corpus_with_reply]
    return Observation(
        primitive=PRIMITIVE_NAME,
        value=round(rate, 6),
        confidence=min(1.0, total / 50),
        window=Window(start_ts=min(ts_vals), end_ts=max(ts_vals)),
        source=f"eyenet/sensor/primitives/conv_init_rate:v{PRIMITIVE_VERSION}",
        evidence_ref=corpus_with_reply[-1][2] if corpus_with_reply else None,
        ts=time.time(),
    )


def compute(
    *,
    corpus: list[tuple[datetime, UUID, str]],  # noqa: ARG001
    bodies: dict[str, str],  # noqa: ARG001
) -> Observation | None:
    """Sync compute signature expected by PrimitiveSpec.

    NOTE: this variant cannot access reply IDs from the sync corpus tuple
    (which carries only ts/id/ref). It returns None and logs a skip warning.
    The sensor calls `compute_async` directly after fetching reply-aware corpus.
    This stub satisfies the PrimitiveSpec interface for type-checking only.
    """
    return None


__all__ = [
    "MIN_MESSAGES",
    "PRIMITIVE_NAME",
    "PRIMITIVE_VERSION",
    "compute",
    "compute_async",
]
