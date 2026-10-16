# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the per-entity note handlers (/v1/notes)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser, ResourceNotFound, ScopeForbidden
from eyenet.api.v1.notes.api_delete_note import notes_delete
from eyenet.api.v1.notes.api_get_note import notes_get
from eyenet.api.v1.notes.api_set_note import notes_set
from eyenet.api.v1.schemas.entity_notes import SetNoteRequest
from eyenet.contracts.document import DocumentRow
from eyenet.contracts.enums import ClearanceScope, SensitivityTier
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


async def test_set_get_delete_and_upsert(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser("write:graph", "read:graph")
    ent = uuid4()
    created = await notes_set(SetNoteRequest(body="v1"), user, storage, "actor", ent)
    assert created.body == "v1"
    assert created.entity_type == "actor"
    got = await notes_get(user, storage, "actor", ent)
    assert got.id == created.id
    # upsert returns the same row with the new body; original author is preserved
    other = mkuser("write:graph")
    updated = await notes_set(SetNoteRequest(body="v2"), other, storage, "actor", ent)
    assert updated.id == created.id
    assert updated.body == "v2"
    assert updated.created_by_user_id == user.user_id
    await notes_delete(user, storage, "actor", ent)
    with pytest.raises(ResourceNotFound):
        await notes_get(user, storage, "actor", ent)
    await storage.close()


async def test_404s(storage: BaseRepository, mkuser: Callable[..., CurrentUser]) -> None:
    user = mkuser("write:graph", "read:graph")
    with pytest.raises(ResourceNotFound):
        await notes_get(user, storage, "actor", uuid4())
    with pytest.raises(ResourceNotFound):
        await notes_delete(user, storage, "actor", uuid4())
    await storage.close()


async def test_note_on_restricted_document_is_tier_gated(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    now = datetime.now(tz=UTC)
    doc_id = await storage.put_document(
        DocumentRow(
            sha256=uuid4().hex + uuid4().hex,
            mime="application/pdf",
            size_bytes=10,
            storage_uri="/data/x.bin",
            uploaded_at=now,
            ingested_at=now,
            classifier_tier=SensitivityTier.RESTRICTED,
        )
    )
    uncleared = mkuser("write:graph", "read:graph")
    # a note keyed to a restricted document must not be set/read/deleted uncleared
    with pytest.raises(ScopeForbidden):
        await notes_set(SetNoteRequest(body="x"), uncleared, storage, "document", doc_id)
    with pytest.raises(ScopeForbidden):
        await notes_get(uncleared, storage, "document", doc_id)
    with pytest.raises(ScopeForbidden):
        await notes_delete(uncleared, storage, "document", doc_id)
    # cleared operator can write then read it
    cleared = mkuser("write:graph", "read:graph", ClearanceScope.READ_RESTRICTED.value)
    note = await notes_set(SetNoteRequest(body="seen"), cleared, storage, "document", doc_id)
    assert note.body == "seen"
    assert (await notes_get(cleared, storage, "document", doc_id)).id == note.id
    await storage.close()
