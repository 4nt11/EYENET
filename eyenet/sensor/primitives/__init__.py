"""EYENET primitive registry.

Each `PrimitiveSpec` binds a BEHAVE-TEXT primitive name to its compute
function. `StylometricSensor` iterates `PRIMITIVES` on every raw message.

Primitives that need reply-graph data (e.g. `conversation_initiation_rate`)
set `requires_reply_corpus=True` and provide `compute_with_reply`. The
sensor fetches the reply-aware corpus and calls that function instead.
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
)

__all__ = ["PRIMITIVES", "PrimitiveSpec"]
