# SPDX-License-Identifier: AGPL-3.0-or-later
"""Topic → ``stream:*`` scope mapping (M9.A5).

The wire-level :class:`StreamTopic` selector names a bus-subject family; the
authority to subscribe to it is a ``stream:*`` scope in the caller's
``effective_scopes``. This frozen map is the single source of truth binding
the two, shared by the stream-token mint gate (now) and the SSE delivery path
(streaming milestone). Co-located with the stream surface rather than in
``api.auth._permissions`` — the latter is contracts-layer and must not import
the ``api.v1`` ``StreamTopic`` enum.
"""

from __future__ import annotations

from collections.abc import Mapping

from eyenet.api.v1.schemas.enums import StreamTopic

STREAM_TOPIC_SCOPE: Mapping[StreamTopic, str] = {
    StreamTopic.ATTRIBUTION_LINKAGE: "stream:linkages",
    StreamTopic.ATTRIBUTION_PERSONA: "stream:personas",
    StreamTopic.EYENET_AUDIT: "stream:audit",
    StreamTopic.EYENET_CONTROL: "stream:control",
}

__all__ = ["STREAM_TOPIC_SCOPE"]
