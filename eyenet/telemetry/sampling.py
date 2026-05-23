"""Trace sampling predicate hook (PLAN §8.6).

v0: 100% sampling, full attributes. The predicate `should_keep_trace` is
wired now with a `return True` body so M2+ can flip to tail-sampling without
retrofitting every span emitter.

Future predicate (sketch): keep traces where `attribution.linkage.proposed`
is emitted or any span is errored; sample the rest.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class _SpanLike(Protocol):
    name: str
    attributes: dict[str, object]
    status: object


def should_keep_trace(
    root_span: _SpanLike,
    span_tree: Sequence[_SpanLike],
) -> bool:
    """Return True iff this trace should be exported.

    v0 default: keep everything. Tail-sampling logic lands when the
    primitive suite stabilizes.
    """

    _ = (root_span, span_tree)
    return True


__all__ = ["should_keep_trace"]
