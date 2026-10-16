# SPDX-License-Identifier: AGPL-3.0-or-later
"""EntityNotesMixin — one operator note per entity (upsert / get / delete)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 5, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def test_set_get_delete(storage: BaseRepository) -> None:
    user = uuid4()
    ent = uuid4()
    assert await storage.get_entity_note(entity_type="actor", entity_id=ent) is None
    nid = await storage.set_entity_note(
        entity_type="actor", entity_id=ent, body="suspicious", created_by_user_id=user, now=_NOW
    )
    note = await storage.get_entity_note(entity_type="actor", entity_id=ent)
    assert note is not None
    assert note.body == "suspicious"
    assert note.created_by_user_id == user
    # delete
    assert await storage.delete_entity_note(entity_type="actor", entity_id=ent) is True
    assert await storage.get_entity_note(entity_type="actor", entity_id=ent) is None
    assert await storage.delete_entity_note(entity_type="actor", entity_id=ent) is False
    assert nid  # id was returned
    await storage.close()


async def test_upsert_preserves_identity(storage: BaseRepository) -> None:
    user = uuid4()
    ent = uuid4()
    first = await storage.set_entity_note(
        entity_type="artifact", entity_id=ent, body="v1", created_by_user_id=user, now=_NOW
    )
    second = await storage.set_entity_note(
        entity_type="artifact",
        entity_id=ent,
        body="v2",
        created_by_user_id=uuid4(),  # a different editor
        now=_NOW + timedelta(hours=1),
    )
    assert second == first  # same row (upsert, not a new note)
    note = await storage.get_entity_note(entity_type="artifact", entity_id=ent)
    assert note is not None
    assert note.body == "v2"
    assert note.created_by_user_id == user  # original author preserved
    assert note.updated_at > note.created_at
    await storage.close()
