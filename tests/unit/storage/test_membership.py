"""Unit tests for upsert_membership: the actor<->group role primitive (MODELS §2.2).

The cross-platform rank home — Discord rank, IRC user mode, Matrix power level.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts.enums import GroupKind, MembershipRole, SourceKind
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.fixture
async def ids(storage: BaseRepository) -> tuple[UUID, UUID]:
    source_id = await storage.upsert_source(
        kind=SourceKind.DISCORD, display_name="discord:test", created_at=_NOW
    )
    actor_id, _ = await storage.upsert_actor(
        source_id=source_id,
        actor_key="actor:" + "d" * 64,
        platform_userid="1335682327006679070",
        handle="returnero",
        display_name="mf$",
        seen_at=_NOW,
    )
    group_id, _ = await storage.upsert_group(
        source_id=source_id, platform_groupid="g1", kind=GroupKind.CHAT,
        title="MortemTeam", seen_at=_NOW,
    )
    return actor_id, group_id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_then_role_change(storage: BaseRepository, ids: tuple[UUID, UUID]) -> None:
    actor_id, group_id = ids
    mid, changed = await storage.upsert_membership(
        actor_id=actor_id, group_id=group_id, role=MembershipRole.MEMBER, seen_at=_NOW
    )
    assert changed is True  # newly created
    mid2, changed2 = await storage.upsert_membership(
        actor_id=actor_id, group_id=group_id, role=MembershipRole.ADMIN, seen_at=_NOW
    )
    assert mid2 == mid  # same row: unique on (actor_id, group_id)
    assert changed2 is True  # MEMBER -> ADMIN is a real change


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotent_same_role(storage: BaseRepository, ids: tuple[UUID, UUID]) -> None:
    actor_id, group_id = ids
    _, c1 = await storage.upsert_membership(
        actor_id=actor_id, group_id=group_id, role=MembershipRole.ADMIN, seen_at=_NOW
    )
    _, c2 = await storage.upsert_membership(
        actor_id=actor_id, group_id=group_id, role=MembershipRole.ADMIN, seen_at=_NOW
    )
    assert c1 is True  # created
    assert c2 is False  # same role -> no change
