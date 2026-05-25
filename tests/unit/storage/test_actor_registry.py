"""Unit tests for the flat repo's actor/source upsert + resolve methods."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlmodel import select

from eyenet.contracts.enums import SourceKind
from eyenet.models import ActorTable
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.fixture
async def source_id(storage: BaseRepository) -> UUID:
    return await storage.upsert_source(
        kind=SourceKind.TELEGRAM,
        display_name="telegram:test",
        created_at=_NOW,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_unknown_returns_none(storage: BaseRepository) -> None:
    assert await storage.resolve_actor_id("actor:" + "a" * 64) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_and_resolve(storage: BaseRepository, source_id: UUID) -> None:
    actor_key = "actor:" + "b" * 64
    uid = await storage.upsert_actor(
        source_id=source_id,
        actor_key=actor_key,
        platform_userid="12345",
        handle="@testuser",
        display_name="Test User",
        seen_at=_NOW,
    )
    resolved = await storage.resolve_actor_id(actor_key)
    assert resolved == uid


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_idempotent(storage: BaseRepository, source_id: UUID) -> None:
    actor_key = "actor:" + "c" * 64
    uid1 = await storage.upsert_actor(
        source_id=source_id,
        actor_key=actor_key,
        platform_userid="99",
        handle=None,
        display_name=None,
        seen_at=_NOW,
    )
    uid2 = await storage.upsert_actor(
        source_id=source_id,
        actor_key=actor_key,
        platform_userid="99",
        handle="@newhandle",
        display_name="New Name",
        seen_at=_NOW,
    )
    assert uid1 == uid2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_updates_handle(storage: BaseRepository, source_id: UUID) -> None:
    actor_key = "actor:" + "d" * 64
    await storage.upsert_actor(
        source_id=source_id,
        actor_key=actor_key,
        platform_userid="77",
        handle="@old",
        display_name=None,
        seen_at=_NOW,
    )
    await storage.upsert_actor(
        source_id=source_id,
        actor_key=actor_key,
        platform_userid="77",
        handle="@new",
        display_name=None,
        seen_at=_NOW,
    )
    async with storage.session() as session:
        result = await session.exec(
            select(ActorTable).where(ActorTable.actor_key == actor_key)
        )
        row = result.first()
    assert row is not None
    assert row.current_handle == "@new"
