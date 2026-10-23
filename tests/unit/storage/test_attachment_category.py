# SPDX-License-Identifier: AGPL-3.0-or-later
"""Attachment collection-class ``category`` mixin: set/clear + list (processing queue).

Types against BaseRepository + constructs via get_repository (Rule 2).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from eyenet.contracts.enums import AttachmentKind
from eyenet.contracts.message import AttachmentRow
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_STEALER = "stealer_logs"


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _put(storage: BaseRepository, *, sha: str, storage_uri: str | None) -> object:
    return await storage.put_attachment(
        AttachmentRow(
            message_id=uuid4(),
            kind=AttachmentKind.DOCUMENT,
            mime="application/x-rar-compressed",
            size_bytes=1_000_000,
            sha256=sha,
            storage_uri=storage_uri,
        )
    )


async def test_set_category_marks_and_clears(storage: BaseRepository) -> None:
    aid = await _put(storage, sha="a" * 64, storage_uri="blob/a.bin")
    got = await storage.get_attachment(aid)
    assert got is not None and got.category is None  # default

    assert await storage.set_attachment_category(aid, _STEALER) is True
    got = await storage.get_attachment(aid)
    assert got is not None and got.category == _STEALER

    assert await storage.set_attachment_category(aid, None) is True  # clear
    got = await storage.get_attachment(aid)
    assert got is not None and got.category is None
    await storage.close()


async def test_set_category_unknown_returns_false(storage: BaseRepository) -> None:
    assert await storage.set_attachment_category(uuid4(), _STEALER) is False
    await storage.close()


async def test_list_by_category_and_stored_only(storage: BaseRepository) -> None:
    marked_stored = await _put(storage, sha="b" * 64, storage_uri="blob/b.bin")
    marked_shell = await _put(storage, sha="c" * 64, storage_uri=None)  # over-gate, no blob
    await _put(storage, sha="d" * 64, storage_uri="blob/d.bin")  # unmarked
    await storage.set_attachment_category(marked_stored, _STEALER)
    await storage.set_attachment_category(marked_shell, _STEALER)

    all_marked = await storage.list_attachments_by_category(_STEALER, limit=10)
    assert {r.id for r in all_marked} == {marked_stored, marked_shell}

    # The pipeline only wants blobs it can actually read.
    stored = await storage.list_attachments_by_category(_STEALER, stored_only=True, limit=10)
    assert [r.id for r in stored] == [marked_stored]
    await storage.close()
