# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit test for GET /v1/documents (documents_list).

Bypasses ASGI routing (coverage can't trace it). Authenticated-only, all rows —
metadata surface, no bytes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser
from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.documents.api_list_documents import documents_list
from eyenet.contracts.document import DocumentRow
from eyenet.contracts.enums import SensitivityTier
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)


def _row(**over: object) -> DocumentRow:
    base: dict[str, object] = {
        "sha256": uuid4().hex + uuid4().hex,
        "mime": "application/pdf",
        "size_bytes": 2048,
        "doc_kind": "pdf",
        "filename": "memo.pdf",
        "storage_uri": "/data/x.bin",
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


async def test_list_projects_summaries(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    await storage.put_document(_row())
    page = CursorParams(offset=0, limit=50, include_total=True)
    res = await documents_list(mkuser(), storage, page, doc_kind=None, review_required=None)
    assert len(res.items) == 1
    assert res.estimated_total == 1
    assert res.items[0].filename == "memo.pdf"
    assert res.items[0].mime == "application/pdf"


async def test_effective_tier_reflects_override(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    await storage.put_document(
        _row(
            classifier_tier=SensitivityTier.NORMAL,
            operator_tier_override=SensitivityTier.RESTRICTED,
        )
    )
    page = CursorParams(offset=0, limit=50, include_total=False)
    res = await documents_list(mkuser(), storage, page, doc_kind=None, review_required=None)
    item = res.items[0]
    assert item.classifier_tier is SensitivityTier.NORMAL
    assert item.tier is SensitivityTier.RESTRICTED
    assert res.estimated_total is None  # not requested


async def test_empty_list(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    page = CursorParams(offset=0, limit=50, include_total=True)
    res = await documents_list(mkuser(), storage, page, doc_kind=None, review_required=None)
    assert res.items == []
    assert res.estimated_total == 0
