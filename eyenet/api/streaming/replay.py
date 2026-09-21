# SPDX-License-Identifier: AGPL-3.0-or-later
"""StreamReplaySource — gap-free reconnect from the durable event log (§6.5, §11.5).

On ``Last-Event-ID`` the SSE handler replays every durable event with
``event_id > cursor`` before switching to bus live-tail. Reads storage only —
bus-agnostic, so MemoryBus / NATS-core / JetStream replay identically.

Only *operator state-transitions* are logged (§11.5), so only those replay:

- ``attribution.linkage.*``  → ``linkage_event_log``
- ``attribution.persona.*``  → ``persona_event_log``
- ``eyenet.identity.released`` (a control-stream subject) → ``identity_event_log``

The audit stream has no event log — the ``eyenet.audit.*`` hash chain serves that
role — so it never replays (live-tail only). ``eyenet.control.panic`` and
``eyenet.identity.freeze_all`` are fleet actions with no per-entity log row, so
they contribute nothing to replay either (live-only; also durable in the audit
chain per §3.5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection
    from uuid import UUID

    from eyenet.contracts.event_log import EventLogRow
    from eyenet.storage.repository import BaseRepository

# Topic values (mirror ``StreamTopic`` in eyenet.api.v1.schemas.enums). Kept as
# bare strings so this bus-facing layer does not import the v1 schema package —
# see the circular-import note in this module's package sibling ``sse``.
_LINKAGE = "attribution.linkage"
_PERSONA = "attribution.persona"
_CONTROL = "eyenet.control"

# The control stream (§3.5) surfaces only these identity subjects. The rest of
# identity_event_log (claimed/frozen/burned) belongs to no stream topic.
_CONTROL_IDENTITY_SUBJECTS = frozenset({"eyenet.identity.released"})

# Default replay page. One reconnect drains as many pages as needed (the handler
# loops until a page comes back short); the cap only bounds a single round-trip.
DEFAULT_PAGE = 512


class StreamReplaySource:
    """Reads the event-log tables for the topics a connection is authorized for."""

    def __init__(self, storage: BaseRepository) -> None:
        self._storage = storage

    async def replay(
        self,
        topics: Collection[str],
        after_event_id: UUID | None,
        limit: int = DEFAULT_PAGE,
    ) -> list[EventLogRow]:
        """One event_id-ordered page of durable events across the given topics.

        ``topics`` are ``StreamTopic`` *values* (bus-subject prefixes). Merged
        across tables and truncated to ``limit``; the handler advances the cursor
        to the last row and re-calls until a page returns fewer than ``limit``
        (drained). Truncated-off rows re-appear next page — no gap.
        """
        rows: list[EventLogRow] = []
        if _LINKAGE in topics:
            rows += await self._storage.linkage_events_since(after_event_id, limit)
        if _PERSONA in topics:
            rows += await self._storage.persona_events_since(after_event_id, limit)
        if _CONTROL in topics:
            rows += [
                r
                for r in await self._storage.identity_events_since(after_event_id, limit)
                if r.event_subject in _CONTROL_IDENTITY_SUBJECTS
            ]
        # eyenet.audit: hash chain, no event log → nothing to replay.
        rows.sort(key=lambda r: str(r.event_id))
        return rows[:limit]


__all__ = ["DEFAULT_PAGE", "StreamReplaySource"]
