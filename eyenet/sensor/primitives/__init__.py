"""EYENET primitive registry.

Each `PrimitiveSpec` binds a BEHAVE-TEXT primitive name to its compute
function. `StylometricSensor` iterates `PRIMITIVES` on every raw message.

Primitives that need reply-graph data (e.g. `conversation_initiation_rate`)
set `requires_reply_corpus=True` and provide `compute_with_reply`. The
sensor fetches the reply-aware corpus and calls that function instead.

Primitives whose semantics are corpus-level rather than window-level
(`meta.*` — total_messages, span, rates, etc.) set
`requires_full_corpus=True`. The sensor then passes the full per-actor
history (cursor sentinels of epoch/null UUID) rather than the
since-cursor delta. Cursors still advance normally — they're a no-op for
meta primitives.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from behave_text.spec import Observation

from . import (
    character_ngram_simhash,
    conversation_initiation_rate,
    distinctive_vocabulary_signature,
    function_word_distribution_top50,
    mattr,
    message_length,
    meta_active_days,
    meta_activity_density,
    meta_corpus_span_days,
    meta_fingerprint_confidence,
    meta_first_seen_ts,
    meta_last_seen_ts,
    meta_msg_per_day,
    meta_total_messages,
    punctuation_style,
    typo_signature,
)

ComputeFn = Callable[
    ...,  # keyword-only: corpus + bodies
    "Observation | None",
]

AsyncComputeWithReplyFn = Callable[
    ...,  # keyword-only: corpus_with_reply
    "Awaitable[Observation | None]",
]


@dataclass(frozen=True)
class PrimitiveSpec:
    name: str
    version: str
    compute: ComputeFn
    # Set to True for primitives that need `reply_to_msg_id` per corpus row.
    requires_reply_corpus: bool = False
    # Async compute used when `requires_reply_corpus=True`; ignored otherwise.
    compute_with_reply: AsyncComputeWithReplyFn | None = field(default=None, compare=False)
    # Set to True for primitives whose semantics are corpus-level rather than
    # window-level (e.g. meta.*). The sensor passes the full per-actor
    # history regardless of cursor state.
    requires_full_corpus: bool = False


PRIMITIVES: tuple[PrimitiveSpec, ...] = (
    PrimitiveSpec(
        name=function_word_distribution_top50.PRIMITIVE_NAME,
        version=function_word_distribution_top50.PRIMITIVE_VERSION,
        compute=function_word_distribution_top50.compute,
    ),
    PrimitiveSpec(
        name=character_ngram_simhash.PRIMITIVE_NAME,
        version=character_ngram_simhash.PRIMITIVE_VERSION,
        compute=character_ngram_simhash.compute,
    ),
    PrimitiveSpec(
        name=distinctive_vocabulary_signature.PRIMITIVE_NAME,
        version=distinctive_vocabulary_signature.PRIMITIVE_VERSION,
        compute=distinctive_vocabulary_signature.compute,
    ),
    PrimitiveSpec(
        name=mattr.PRIMITIVE_NAME,
        version=mattr.PRIMITIVE_VERSION,
        compute=mattr.compute,
    ),
    PrimitiveSpec(
        name=message_length.PRIMITIVE_NAME_CLASS,
        version=message_length.PRIMITIVE_VERSION,
        compute=message_length.compute_class,
    ),
    PrimitiveSpec(
        name=message_length.PRIMITIVE_NAME_VARIANCE,
        version=message_length.PRIMITIVE_VERSION,
        compute=message_length.compute_variance,
    ),
    PrimitiveSpec(
        name=punctuation_style.PRIMITIVE_NAME,
        version=punctuation_style.PRIMITIVE_VERSION,
        compute=punctuation_style.compute,
    ),
    PrimitiveSpec(
        name=typo_signature.PRIMITIVE_NAME,
        version=typo_signature.PRIMITIVE_VERSION,
        compute=typo_signature.compute,
    ),
    PrimitiveSpec(
        name=conversation_initiation_rate.PRIMITIVE_NAME,
        version=conversation_initiation_rate.PRIMITIVE_VERSION,
        compute=conversation_initiation_rate.compute,
        requires_reply_corpus=True,
        compute_with_reply=conversation_initiation_rate.compute_async,
    ),
    # ── meta.* (corpus-level, see BEHAVE-TEXT 0.1.2) ─────────────────────
    PrimitiveSpec(
        name=meta_total_messages.PRIMITIVE_NAME,
        version=meta_total_messages.PRIMITIVE_VERSION,
        compute=meta_total_messages.compute,
        requires_full_corpus=True,
    ),
    PrimitiveSpec(
        name=meta_corpus_span_days.PRIMITIVE_NAME,
        version=meta_corpus_span_days.PRIMITIVE_VERSION,
        compute=meta_corpus_span_days.compute,
        requires_full_corpus=True,
    ),
    PrimitiveSpec(
        name=meta_msg_per_day.PRIMITIVE_NAME,
        version=meta_msg_per_day.PRIMITIVE_VERSION,
        compute=meta_msg_per_day.compute,
        requires_full_corpus=True,
    ),
    PrimitiveSpec(
        name=meta_active_days.PRIMITIVE_NAME,
        version=meta_active_days.PRIMITIVE_VERSION,
        compute=meta_active_days.compute,
        requires_full_corpus=True,
    ),
    PrimitiveSpec(
        name=meta_activity_density.PRIMITIVE_NAME,
        version=meta_activity_density.PRIMITIVE_VERSION,
        compute=meta_activity_density.compute,
        requires_full_corpus=True,
    ),
    PrimitiveSpec(
        name=meta_first_seen_ts.PRIMITIVE_NAME,
        version=meta_first_seen_ts.PRIMITIVE_VERSION,
        compute=meta_first_seen_ts.compute,
        requires_full_corpus=True,
    ),
    PrimitiveSpec(
        name=meta_last_seen_ts.PRIMITIVE_NAME,
        version=meta_last_seen_ts.PRIMITIVE_VERSION,
        compute=meta_last_seen_ts.compute,
        requires_full_corpus=True,
    ),
    PrimitiveSpec(
        name=meta_fingerprint_confidence.PRIMITIVE_NAME,
        version=meta_fingerprint_confidence.PRIMITIVE_VERSION,
        compute=meta_fingerprint_confidence.compute,
        requires_full_corpus=True,
    ),
)

__all__ = ["PRIMITIVES", "PrimitiveSpec"]
