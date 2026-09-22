# SPDX-License-Identifier: AGPL-3.0-or-later
"""list_documents / count_documents (DocumentsMixin, M10 viewer list).

Types against BaseRepository + constructs via get_repository per Rule 2
([[feedback_use_basereo_abstraction_in_tests]]).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from eyenet.contracts.document import DocumentRow
from eyenet.contracts.enums import SensitivityTier
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _hex64() -> str:
    return uuid4().hex + uuid4().hex


def _row(**over: object) -> DocumentRow:
    base: dict[str, object] = {
        "sha256": _hex64(),
        "mime": "application/pdf",
        "size_bytes": 2048,
        "doc_kind": "pdf",
        "filename": "memo.pdf",
        "storage_uri": "/data/documents/x.bin",
        "extracted_text": "hello",
        "embedded_meta": {},
        "classification": {},
        "review_required": False,
        "uploaded_at": _NOW,
        "ingested_at": _NOW,
        "classifier_tier": SensitivityTier.NORMAL,
    }
    base.update(over)
    return DocumentRow(**base)  # type: ignore[arg-type]


async def test_list_empty(storage: BaseRepository) -> None:
    assert await storage.list_documents(limit=10) == []
    assert await storage.count_documents() == 0


async def test_list_all_newest_first(storage: BaseRepository) -> None:
    await storage.put_document(_row(uploaded_at=_NOW, filename="old.pdf"))
    await storage.put_document(_row(uploaded_at=_NOW + timedelta(hours=1), filename="new.pdf"))
    rows = await storage.list_documents(limit=10)
    assert [r.filename for r in rows] == ["new.pdf", "old.pdf"]
    assert await storage.count_documents() == 2


async def test_filter_doc_kind(storage: BaseRepository) -> None:
    await storage.put_document(_row(doc_kind="pdf"))
    await storage.put_document(_row(doc_kind="image", filename="p.png"))
    rows = await storage.list_documents(doc_kind="image", limit=10)
    assert [r.filename for r in rows] == ["p.png"]
    assert await storage.count_documents(doc_kind="image") == 1


async def test_filter_review_required(storage: BaseRepository) -> None:
    await storage.put_document(_row(review_required=True))
    await storage.put_document(_row(review_required=False))
    assert len(await storage.list_documents(review_required=True, limit=10)) == 1
    assert await storage.count_documents(review_required=True) == 1


async def test_limit_offset_paginate(storage: BaseRepository) -> None:
    for i in range(3):
        await storage.put_document(_row(uploaded_at=_NOW + timedelta(hours=i)))
    page1 = await storage.list_documents(limit=2, offset=0)
    page2 = await storage.list_documents(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 1
