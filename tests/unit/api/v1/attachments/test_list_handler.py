# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit test for GET /v1/attachments (attachments_list)."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser
from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.attachments.api_list_attachments import attachments_list
from eyenet.contracts.enums import AttachmentKind, SensitivityTier
from eyenet.contracts.message import AttachmentRow
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


async def _put(storage: BaseRepository, *, mime: str = "image/png"):
    return await storage.put_attachment(
        AttachmentRow(
            message_id=uuid4(),
            kind=AttachmentKind.DOCUMENT,
            mime=mime,
            size_bytes=11,
            sha256=uuid4().hex + uuid4().hex,
            storage_uri="blob/x.bin",
            classifier_tier=SensitivityTier.NORMAL,
        )
    )


async def test_list_projects_summaries(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    blob_id = await _put(storage)
    page = CursorParams(offset=0, limit=50, include_total=True)
    res = await attachments_list(mkuser(), storage, page, mime=None)
    assert len(res.items) == 1
    assert res.items[0].blob_id == blob_id
    assert res.items[0].mime == "image/png"
    assert res.items[0].kind == str(AttachmentKind.DOCUMENT)
    assert res.estimated_total == 1


async def test_mime_filter(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    await _put(storage, mime="image/png")
    await _put(storage, mime="application/pdf")
    page = CursorParams(offset=0, limit=50, include_total=False)
    res = await attachments_list(mkuser(), storage, page, mime="application/pdf")
    assert len(res.items) == 1
    assert res.items[0].mime == "application/pdf"


async def test_empty_list(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    page = CursorParams(offset=0, limit=50, include_total=True)
    res = await attachments_list(mkuser(), storage, page, mime=None)
    assert res.items == []
    assert res.estimated_total == 0
