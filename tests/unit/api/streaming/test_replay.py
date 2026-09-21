# SPDX-License-Identifier: AGPL-3.0-or-later
"""StreamReplaySource — cross-parent, event_id-ordered replay (M9.H1)."""

from __future__ import annotations

from uuid import UUID

import pytest
from uuid_extensions import uuid7

from eyenet.api.streaming.replay import StreamReplaySource
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_TP = "00-" + "0" * 32 + "-" + "0" * 16 + "-01"


def _uid() -> UUID:
    return UUID(str(uuid7()))


async def _seed_linkage(storage: BaseRepository, subject: str) -> UUID:
    eid = _uid()
    await storage.append_linkage_event(
        linkage_id=_uid(), event_subject=subject, event_id=eid, traceparent=_TP
    )
    return eid


async def _seed_persona(storage: BaseRepository, subject: str) -> UUID:
    eid = _uid()
    await storage.append_persona_event(
        persona_id=_uid(), event_subject=subject, event_id=eid, traceparent=_TP
    )
    return eid


async def _seed_identity(storage: BaseRepository, subject: str) -> UUID:
    eid = _uid()
    await storage.append_identity_event(
        identity_id=_uid(), event_subject=subject, event_id=eid, traceparent=_TP
    )
    return eid


async def test_replay_merges_and_orders_by_event_id(storage: BaseRepository) -> None:
    # Interleave two tables; event_ids are uuid7 so append order == event_id order.
    e1 = await _seed_linkage(storage, "attribution.linkage.proposed")
    e2 = await _seed_persona(storage, "attribution.persona.updated")
    e3 = await _seed_linkage(storage, "attribution.linkage.confirmed")

    src = StreamReplaySource(storage)
    rows = await src.replay(["attribution.linkage", "attribution.persona"], None)
    assert [r.event_id for r in rows] == [e1, e2, e3]


async def test_replay_after_cursor_excludes_seen(storage: BaseRepository) -> None:
    e1 = await _seed_linkage(storage, "attribution.linkage.proposed")
    e2 = await _seed_linkage(storage, "attribution.linkage.confirmed")

    src = StreamReplaySource(storage)
    rows = await src.replay(["attribution.linkage"], e1)
    assert [r.event_id for r in rows] == [e2]


async def test_control_topic_filters_identity_to_released(storage: BaseRepository) -> None:
    await _seed_identity(storage, "eyenet.identity.claimed")
    released = await _seed_identity(storage, "eyenet.identity.released")
    await _seed_identity(storage, "eyenet.identity.frozen")

    src = StreamReplaySource(storage)
    rows = await src.replay(["eyenet.control"], None)
    # Only `released` has a stream on the control topic; the rest of the identity
    # log belongs to no stream (§3.5).
    assert [r.event_id for r in rows] == [released]


async def test_audit_topic_never_replays(storage: BaseRepository) -> None:
    await _seed_linkage(storage, "attribution.linkage.proposed")
    src = StreamReplaySource(storage)
    # eyenet.audit has no event log — the hash chain serves replay.
    assert await src.replay(["eyenet.audit"], None) == []


async def test_replay_page_truncates_to_limit(storage: BaseRepository) -> None:
    for _ in range(5):
        await _seed_linkage(storage, "attribution.linkage.proposed")
    src = StreamReplaySource(storage)
    page = await src.replay(["attribution.linkage"], None, limit=2)
    assert len(page) == 2
