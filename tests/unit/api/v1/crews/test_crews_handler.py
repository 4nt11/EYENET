# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the manual-crew CRUD handlers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.api.deps import CurrentUser, ResourceNotFound
from eyenet.api.v1.crews.api_crews import (
    crews_add_member,
    crews_create,
    crews_delete,
    crews_get,
    crews_list,
    crews_remove_member,
)
from eyenet.api.v1.schemas.manual_crews import AddCrewMemberRequest, CreateManualCrewRequest
from eyenet.contracts.enums import SourceKind
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


async def _actor(storage: BaseRepository, key: str, handle: str) -> UUID:
    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=_NOW)
    return await storage.upsert_actor(
        source_id=src, actor_key=key, platform_userid=key[-4:], handle=handle,
        display_name=handle.lstrip("@").title(), seen_at=_NOW,
    )


async def test_crew_lifecycle(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser("write:actors", "read:actors")
    alice = await _actor(storage, "tg:alice", "@alice")
    bob = await _actor(storage, "tg:bob", "@bob")

    created = await crews_create(
        CreateManualCrewRequest(name="The Gentlemen", notes="doxbyte"), user, storage
    )
    cid = created.crew_id

    listed = await crews_list(user, storage)
    assert listed.count == 1
    assert listed.items[0].name == "The Gentlemen"
    assert listed.items[0].member_count == 0

    # add by actor_id, then by handle
    d = await crews_add_member(cid, AddCrewMemberRequest(actor_id=alice), user, storage)
    assert {m.actor_id for m in d.members} == {alice}
    d = await crews_add_member(cid, AddCrewMemberRequest(handle="@bob"), user, storage)
    assert {m.actor_id for m in d.members} == {alice, bob}
    # idempotent
    d = await crews_add_member(cid, AddCrewMemberRequest(actor_id=alice), user, storage)
    assert len(d.members) == 2

    # remove one
    d = await crews_remove_member(cid, alice, user, storage)
    assert {m.actor_id for m in d.members} == {bob}

    # delete → gone
    resp = await crews_delete(cid, user, storage)
    assert resp.status_code == 204
    with pytest.raises(ResourceNotFound):
        await crews_get(cid, user, storage)


async def test_add_unknown_handle_404(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser("write:actors", "read:actors")
    created = await crews_create(CreateManualCrewRequest(name="x"), user, storage)
    with pytest.raises(ResourceNotFound):
        await crews_add_member(
            created.crew_id, AddCrewMemberRequest(handle="@ghost"), user, storage
        )


async def test_add_to_missing_crew_404(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser("write:actors", "read:actors")
    alice = await _actor(storage, "tg:alice", "@alice")
    with pytest.raises(ResourceNotFound):
        await crews_add_member(uuid4(), AddCrewMemberRequest(actor_id=alice), user, storage)


def test_add_member_request_requires_exactly_one() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        AddCrewMemberRequest()
    with pytest.raises(ValueError, match="exactly one"):
        AddCrewMemberRequest(actor_id=uuid4(), handle="@x")
