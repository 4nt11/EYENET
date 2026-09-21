# SPDX-License-Identifier: AGPL-3.0-or-later
"""SSE realtime delivery (API_PLAN §3.5, §6.5, §11.4.1 — M9 Group H).

The stream endpoints (`eyenet/api/v1/stream/`) are thin adapters over this
package: authorize the token's topics, then return a ``StreamingResponse`` wrapping
:func:`eyenet.api.streaming.sse.sse_stream`. Replay is served from the durable
event log (:class:`~eyenet.api.streaming.replay.StreamReplaySource`), live-tail
from the bus — bus-agnostic by construction.
"""

from __future__ import annotations

from eyenet.api.streaming.replay import StreamReplaySource
from eyenet.api.streaming.sse import (
    make_sse_response,
    require_topic,
    require_topic_set,
    sse_stream,
)

__all__ = [
    "StreamReplaySource",
    "make_sse_response",
    "require_topic",
    "require_topic_set",
    "sse_stream",
]
