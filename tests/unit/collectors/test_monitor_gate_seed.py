# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ingestion is gated on monitored (joined) groups, not the account's full dialog set.

The Telegram collector seeds ``_monitor_raw_ids`` from its active memberships at
boot (on_subscribe, live-client code that imports telethon/structlog, so it is
coverage-omitted and not importable here). This pins the storage contract that
seed rides on so the gate stays correct: the seed watches exactly the groups this
collector still holds an active membership in — a joined group is covered, a left
group drops out, and a fresh account with no memberships watches nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyenet.contracts.enums import GroupKind, JoinedVia, SourceKind
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _joined_group(storage: BaseRepository, sid, coll_id, platform_groupid: str):
    now = datetime.now(tz=UTC)
    cand = await storage.ensure_candidate(
        source_id=sid, platform_groupid=platform_groupid, seen_at=now
    )
    gid = await storage.upsert_group(
        source_id=sid,
        platform_groupid=platform_groupid,
        kind=GroupKind.CHANNEL,
        title="g",
        seen_at=now,
    )
    await storage.open_membership(
        collector_id=coll_id,
        group_id=gid,
        joined_at=now,
        joined_via=JoinedVia.CANDIDATE,
        joined_via_candidate_id=cand.id,
    )
    return gid


@pytest.mark.unit
async def test_seed_covers_joined_group(storage: BaseRepository) -> None:
    now = datetime.now(tz=UTC)
    sid = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=now)
    ident = await storage.create_identity(name="tgtest", source_id=sid, session_path="/x")
    coll = await storage.create_collector(
        instance_name="collector-tgtest",
        kind=SourceKind.TELEGRAM,
        source_id=sid,
        identity_id=ident.id,
        config={},
        created_at=now,
        created_by_user_id=ident.id,
    )
    # A group we joined via /monitored-groups (numeric, -100-prefixed platform id).
    await _joined_group(storage, sid, coll.id, "-1001174100362")

    # The seed resolves each active membership to its group's platform id.
    seeded: set[str] = set()
    for m in await storage.list_active_memberships(collector_id=coll.id):
        grp = await storage.get_group(m.group_id)
        assert grp is not None
        seeded.add(grp.platform_groupid)

    assert seeded == {"-1001174100362"}


@pytest.mark.unit
async def test_left_group_is_not_seeded(storage: BaseRepository) -> None:
    now = datetime.now(tz=UTC)
    sid = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=now)
    ident = await storage.create_identity(name="tgtest", source_id=sid, session_path="/x")
    coll = await storage.create_collector(
        instance_name="collector-tgtest",
        kind=SourceKind.TELEGRAM,
        source_id=sid,
        identity_id=ident.id,
        config={},
        created_at=now,
        created_by_user_id=ident.id,
    )
    gid = await _joined_group(storage, sid, coll.id, "-1001174100362")
    await storage.close_membership(
        collector_id=coll.id, group_id=gid, left_at=now, left_reason="operator_left"
    )

    # No active memberships → seed is empty → the account ingests nothing until an
    # eye is put on a group.
    assert await storage.list_active_memberships(collector_id=coll.id) == []
