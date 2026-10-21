"""Integration test: the dispatch handler persists member rank end to end.

A GUILD_MEMBER_LIST_UPDATE for returnero (holding the Admin role) must land as an
actor<->guild membership row with role ADMIN, hung off a GroupKind.GUILD node.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlmodel import select

from eyenet.bus import MemoryBus
from eyenet.collectors.discord.real import DiscordCollector
from eyenet.contracts.enums import GroupKind, JoinedVia, MembershipRole, SourceKind
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.models import GroupTable, MembershipTable
from eyenet.storage.factory import get_repository


def _pool(tmp_path: Path) -> FileIdentityPool:
    entry = IdentityFileEntry(name="dc", source=SourceKind.DISCORD, cooldown_seconds=0)
    cfg = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), cfg)
    return FileIdentityPool(cfg, check_session_files=False)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_members_persists_rank(tmp_path: Path) -> None:
    storage = get_repository(in_memory=True)
    now = datetime.now(tz=UTC)
    sid = await storage.upsert_source(kind=SourceKind.DISCORD, display_name="d", created_at=now)

    coll = DiscordCollector(
        bus=MemoryBus(), storage=storage, pool=_pool(tmp_path), identity_name="dc"
    )
    coll._source_uuid = sid
    coll._guild_names["g1"] = "MortemTeam"
    coll._guild_roles["g1"] = {  # Admin role carries the ADMINISTRATOR bit (8)
        "radmin": {"name": "Admin", "permissions": "8"},
        "rtag": {"name": "MortemTeam", "permissions": "0"},
    }

    event = {
        "guild_id": "g1",
        "ops": [{"op": "SYNC", "range": [0, 1], "items": [
            {"group": {"id": "online", "count": 1}},  # section header, skipped
            {"member": {
                "user": {"id": "1335682327006679070", "username": "returnero",
                         "global_name": "mf$"},
                "roles": ["radmin", "rtag"],
            }},
        ]}],
    }
    await coll._handle_members("GUILD_MEMBER_LIST_UPDATE", event)

    async with storage.session() as s:
        memberships = (await s.exec(select(MembershipTable))).all()
        guilds = (await s.exec(select(GroupTable).where(GroupTable.kind == GroupKind.GUILD))).all()

    assert len(guilds) == 1
    assert guilds[0].platform_groupid == "g1"
    assert len(memberships) == 1
    assert memberships[0].role is MembershipRole.ADMIN  # returnero resolved + persisted
    assert memberships[0].group_id == guilds[0].id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rest_404s_retire_dead_channel(tmp_path: Path) -> None:
    """A deleted/recreated channel 404s forever; past the margin the collector retires
    the membership so it stops hammering (regression for the MortemTeam #general nuke)."""
    from eyenet.collectors.discord.real import _MAX_CHANNEL_404

    storage = get_repository(in_memory=True)
    now = datetime.now(tz=UTC)
    sid = await storage.upsert_source(kind=SourceKind.DISCORD, display_name="d", created_at=now)
    gid, _ = await storage.upsert_group(
        source_id=sid, platform_groupid="1561747711072542832",
        kind=GroupKind.CHANNEL, title="general", seen_at=now,
    )
    collector_id = uuid4()  # FK not enforced on in-memory SQLite
    await storage.open_membership(
        collector_id=collector_id, group_id=gid, joined_at=now, joined_via=JoinedVia.SEED
    )

    coll = DiscordCollector(
        bus=MemoryBus(), storage=storage, pool=_pool(tmp_path), identity_name="dc"
    )
    coll._collector_id = collector_id
    coll._chan_group["1561747711072542832"] = gid

    for _ in range(_MAX_CHANNEL_404 - 1):  # under the margin: still monitored
        await coll._note_rest_404("1561747711072542832")
    assert len(await storage.list_active_memberships(collector_id=collector_id)) == 1

    await coll._note_rest_404("1561747711072542832")  # crosses the margin -> retired
    assert await storage.list_active_memberships(collector_id=collector_id) == []
    assert "1561747711072542832" not in coll._chan_404  # counter cleared on retire
