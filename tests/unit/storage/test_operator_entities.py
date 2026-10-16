# SPDX-License-Identifier: AGPL-3.0-or-later
"""OperatorEntitiesMixin — hand-created actors/groups/artifacts for the canvas.

Types against BaseRepository + constructs via get_repository (Rule 2).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 5, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def test_operator_source_is_idempotent(storage: BaseRepository) -> None:
    a = await storage.get_or_create_operator_source(now=_NOW)
    b = await storage.get_or_create_operator_source(now=_NOW)
    assert a == b
    src = await storage.get_source(a)
    assert src is not None
    assert src.kind == SourceKind.OPERATOR
    await storage.close()


async def test_create_operator_actor_sets_provenance(storage: BaseRepository) -> None:
    aid = await storage.create_operator_actor(handle="ghost", display_name=None, now=_NOW)
    actor = await storage.get_actor(aid)
    assert actor is not None
    assert actor.provenance == "operator_asserted"
    assert actor.current_handle == "ghost"
    # a second operator actor is distinct (unique actor_key)
    aid2 = await storage.create_operator_actor(handle="ghost", display_name=None, now=_NOW)
    assert aid2 != aid
    await storage.close()


async def test_create_operator_group_sets_provenance(storage: BaseRepository) -> None:
    gid = await storage.create_operator_group(title="crew chat", kind=GroupKind.CHAT, now=_NOW)
    group = await storage.get_group(gid)
    assert group is not None
    assert group.provenance == "operator_asserted"
    assert group.kind == GroupKind.CHAT
    await storage.close()


async def test_create_operator_artifact_dedups(storage: BaseRepository) -> None:
    first = await storage.create_operator_artifact(kind="onion", value="abc.onion", now=_NOW)
    again = await storage.create_operator_artifact(kind="onion", value="abc.onion", now=_NOW)
    assert first == again  # deduped by value_hash
    other = await storage.create_operator_artifact(kind="onion", value="xyz.onion", now=_NOW)
    assert other != first
    await storage.close()


async def test_collected_upsert_defaults_to_collected(storage: BaseRepository) -> None:
    src = await storage.upsert_source(kind=SourceKind.FORUM, display_name="f", created_at=_NOW)
    actor_id, _ = await storage.upsert_actor(
        source_id=src,
        actor_key="k",
        platform_userid="1",
        handle="h",
        display_name="h",
        seen_at=_NOW,
    )
    actor = await storage.get_actor(actor_id)
    assert actor is not None
    assert actor.provenance == "collected"
    await storage.close()
