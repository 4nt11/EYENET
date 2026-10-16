# SPDX-License-Identifier: AGPL-3.0-or-later
"""The document-source clearance gate on /v1/graph/expand.

Expanding a document is the only place a document's derived data surfaces in the
graph (documents are not search-indexed), so an uncleared caller MUST NOT get past
the gate. Mirrors the document-manifest tier gate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser, ResourceNotFound, ScopeForbidden
from eyenet.api.v1.graph.api_expand import _enforce_document_src_clearance
from eyenet.contracts.document import DocumentRow
from eyenet.contracts.enums import ClearanceScope, SensitivityTier, SystemUserRole
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 5, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _user(*scopes: str) -> CurrentUser:
    return CurrentUser(
        user_id=uuid4(),
        username="op",
        role=SystemUserRole.ANALYST,
        effective_scopes=frozenset({"read:search", *scopes}),
        token_expires_at=None,
    )


async def _doc(storage: BaseRepository, tier: SensitivityTier) -> object:
    return await storage.put_document(
        DocumentRow(
            sha256=uuid4().hex + uuid4().hex,
            mime="application/pdf",
            size_bytes=10,
            storage_uri="/data/x.bin",
            uploaded_at=_NOW,
            ingested_at=_NOW,
            classifier_tier=tier,
        )
    )


async def test_restricted_document_blocks_uncleared(storage: BaseRepository) -> None:
    doc_id = await _doc(storage, SensitivityTier.RESTRICTED)
    with pytest.raises(ScopeForbidden):
        await _enforce_document_src_clearance(storage, _user(), "document", doc_id)
    await storage.close()


async def test_restricted_document_allows_cleared(storage: BaseRepository) -> None:
    doc_id = await _doc(storage, SensitivityTier.RESTRICTED)
    # cleared: has the read:restricted clearance scope -> no raise
    await _enforce_document_src_clearance(
        storage, _user(ClearanceScope.READ_RESTRICTED.value), "document", doc_id
    )
    await storage.close()


async def test_operator_override_tier_is_enforced(storage: BaseRepository) -> None:
    # classifier said NORMAL but an operator promoted to CLASSIFIED -> gate on the override
    doc_id = await _doc(storage, SensitivityTier.NORMAL)
    async with storage.session() as session:
        from eyenet.models.document import DocumentTable

        row = await session.get(DocumentTable, doc_id)
        assert row is not None
        row.operator_tier_override = SensitivityTier.CLASSIFIED
        session.add(row)
        await session.commit()
    with pytest.raises(ScopeForbidden):
        await _enforce_document_src_clearance(
            storage, _user(ClearanceScope.READ_RESTRICTED.value), "document", doc_id
        )
    await storage.close()


async def test_normal_document_needs_no_clearance(storage: BaseRepository) -> None:
    doc_id = await _doc(storage, SensitivityTier.NORMAL)
    await _enforce_document_src_clearance(storage, _user(), "document", doc_id)
    await storage.close()


async def test_unknown_document_is_404(storage: BaseRepository) -> None:
    with pytest.raises(ResourceNotFound):
        await _enforce_document_src_clearance(storage, _user(), "document", uuid4())
    await storage.close()


async def test_non_document_src_is_not_gated(storage: BaseRepository) -> None:
    # an actor/artifact src never touches the document gate (no storage hit, no raise)
    await _enforce_document_src_clearance(storage, _user(), "actor", uuid4())
    await storage.close()
