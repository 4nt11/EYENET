# SPDX-License-Identifier: AGPL-3.0-or-later
"""delete_source / delete_identity: unused deletes succeed, referenced ones 409.

Guards the teardown path for mistaken resources (e.g. a source created on the
wrong platform). An unused source/identity is removable; one that still holds
evidence or is wired to a collector must be refused so nothing is orphaned.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.contracts.enums import (
    GroupKind,
    IdentityState,
    SourceDomainPatternKind,
    SourceKind,
)
from eyenet.storage.errors import ResourceInUseError
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _mk_source(storage: BaseRepository, name: str = "src") -> object:
    return await storage.upsert_source(
        kind=SourceKind.FORUM, display_name=name, created_at=datetime.now(tz=UTC)
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_unused_source_with_domain_succeeds(storage: BaseRepository) -> None:
    sid = await _mk_source(storage)
    await storage.add_source_domain(
        source_id=sid,
        pattern="example.test",
        pattern_kind=SourceDomainPatternKind.EXACT,
        is_primary=True,
        created_at=datetime.now(tz=UTC),
    )
    assert await storage.source_usage(sid) == {}  # nothing references it
    await storage.delete_source(sid)
    assert await storage.get_source(sid) is None
    assert await storage.list_source_domains(source_id=sid) == []  # domains cascaded


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_source_in_use_is_refused(storage: BaseRepository) -> None:
    sid = await _mk_source(storage)
    await storage.upsert_group(
        source_id=sid,
        platform_groupid="g1",
        kind=GroupKind.FORUM_CATEGORY,
        title="t",
        seen_at=datetime.now(tz=UTC),
    )
    assert await storage.source_usage(sid) == {"group": 1}
    with pytest.raises(ResourceInUseError) as ei:
        await storage.delete_source(sid)
    assert ei.value.refs == {"group": 1}
    assert await storage.get_source(sid) is not None  # not deleted


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_missing_source_raises_valueerror(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.delete_source(uuid4())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_unused_identity_succeeds(storage: BaseRepository) -> None:
    sid = await _mk_source(storage)
    ident = await storage.create_identity(name="id1", source_id=sid, session_path="")
    await storage.delete_identity(identity_id=ident.id)
    assert await storage.get_identity(ident.id) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_identity_bound_to_collector_is_refused(storage: BaseRepository) -> None:
    sid = await _mk_source(storage)
    ident = await storage.create_identity(name="id2", source_id=sid, session_path="")
    await storage.create_collector(
        instance_name="forum-collector-1",
        kind=SourceKind.FORUM,
        source_id=sid,
        identity_id=ident.id,
        config={},
        created_at=datetime.now(tz=UTC),
        created_by_user_id=uuid4(),
    )
    with pytest.raises(ResourceInUseError) as ei:
        await storage.delete_identity(identity_id=ident.id)
    assert ei.value.refs.get("collector") == 1
    assert await storage.get_identity(ident.id) is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_stale_in_use_identity_succeeds(storage: BaseRepository) -> None:
    # IN_USE with NO collector is a stale claim — deletable (only a collector
    # binding blocks). Gating on IN_USE alone would deadlock source teardown.
    sid = await _mk_source(storage)
    ident = await storage.create_identity(
        name="id3", source_id=sid, session_path="", state=IdentityState.IN_USE
    )
    await storage.delete_identity(identity_id=ident.id)
    assert await storage.get_identity(ident.id) is None
