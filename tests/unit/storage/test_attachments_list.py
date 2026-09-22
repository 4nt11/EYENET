# SPDX-License-Identifier: AGPL-3.0-or-later
"""list_attachments / count_attachments (AttachmentsMixin, M10 viewer list)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eyenet.contracts.enums import AttachmentKind, SensitivityTier
from eyenet.contracts.message import AttachmentRow
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _hex64() -> str:
    return uuid4().hex + uuid4().hex


async def _put(storage: BaseRepository, *, mime: str = "application/octet-stream"):
    return await storage.put_attachment(
        AttachmentRow(
            message_id=uuid4(),
            kind=AttachmentKind.DOCUMENT,
            mime=mime,
            size_bytes=11,
            sha256=_hex64(),
            storage_uri="blob/x.bin",
            classifier_tier=SensitivityTier.NORMAL,
        )
    )


async def test_list_empty(storage: BaseRepository) -> None:
    assert await storage.list_attachments(limit=10) == []
    assert await storage.count_attachments() == 0


async def test_list_all_newest_first(storage: BaseRepository) -> None:
    # id is uuid7 = time-ordered; the second insert sorts first under id DESC.
    first = await _put(storage)
    second = await _put(storage)
    rows = await storage.list_attachments(limit=10)
    assert [r.id for r in rows] == [second, first]
    assert await storage.count_attachments() == 2


async def test_filter_mime(storage: BaseRepository) -> None:
    await _put(storage, mime="image/png")
    await _put(storage, mime="application/pdf")
    rows = await storage.list_attachments(mime="image/png", limit=10)
    assert len(rows) == 1
    assert rows[0].mime == "image/png"
    assert await storage.count_attachments(mime="image/png") == 1


async def test_limit_offset_paginate(storage: BaseRepository) -> None:
    for _ in range(3):
        await _put(storage)
    assert len(await storage.list_attachments(limit=2, offset=0)) == 2
    assert len(await storage.list_attachments(limit=2, offset=2)) == 1
