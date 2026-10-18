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
from eyenet.api.v1._clearance import enforce_entity_tier_clearance, hidden_tiers_for
from eyenet.api.v1.graph.api_expand import _filter_cleared
from eyenet.contracts.document import DocumentRow
from eyenet.contracts.enums import ClearanceScope, SensitivityTier, SystemUserRole
from eyenet.enrichments.base import ExpandNode
from eyenet.models._base import new_uuid7
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
        await enforce_entity_tier_clearance(storage, _user(), "document", doc_id)
    await storage.close()


async def test_restricted_document_allows_cleared(storage: BaseRepository) -> None:
    doc_id = await _doc(storage, SensitivityTier.RESTRICTED)
    # cleared: has the read:restricted clearance scope -> no raise
    await enforce_entity_tier_clearance(
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
        await enforce_entity_tier_clearance(
            storage, _user(ClearanceScope.READ_RESTRICTED.value), "document", doc_id
        )
    await storage.close()


async def test_normal_document_needs_no_clearance(storage: BaseRepository) -> None:
    doc_id = await _doc(storage, SensitivityTier.NORMAL)
    await enforce_entity_tier_clearance(storage, _user(), "document", doc_id)
    await storage.close()


async def test_unknown_document_is_404(storage: BaseRepository) -> None:
    with pytest.raises(ResourceNotFound):
        await enforce_entity_tier_clearance(storage, _user(), "document", uuid4())
    await storage.close()


async def test_non_document_src_is_not_gated(storage: BaseRepository) -> None:
    # an actor/artifact src never touches the document gate (no storage hit, no raise)
    await enforce_entity_tier_clearance(storage, _user(), "actor", uuid4())
    await storage.close()


# --- per-node neighbour clearance (attachments / future documents on the canvas) ---


def test_hidden_tiers_for_maps_missing_scopes() -> None:
    # no clearance scopes -> both tiers hidden; NORMAL never appears
    assert set(hidden_tiers_for(_user())) == {
        SensitivityTier.RESTRICTED,
        SensitivityTier.CLASSIFIED,
    }
    # read:restricted granted -> only CLASSIFIED remains hidden
    assert hidden_tiers_for(_user(ClearanceScope.READ_RESTRICTED.value)) == [
        SensitivityTier.CLASSIFIED
    ]


def _att(tier: str) -> ExpandNode:
    return ExpandNode(
        entity_type="attachment",
        entity_id=new_uuid7(),
        title="f",
        status=None,
        source_id=None,
        fields={"tier": tier},
    )


def test_filter_cleared_drops_overclearance_neighbour_and_its_edge() -> None:
    src = new_uuid7()
    ok, gated = _att("normal"), _att("classified")
    rows = [ok, gated]
    edges = [
        {"src_id": src, "dst_id": ok.entity_id, "kind": "attached"},
        {"src_id": src, "dst_id": gated.entity_id, "kind": "attached"},
    ]
    kept, pruned = _filter_cleared(rows, edges, _user())  # no clearance
    assert [n.entity_id for n in kept] == [ok.entity_id]
    assert [e["dst_id"] for e in pruned] == [ok.entity_id]  # edge to gated node dropped


def test_filter_cleared_passes_everything_when_cleared() -> None:
    src = new_uuid7()
    rows = [_att("normal"), _att("classified")]
    edges = [{"src_id": src, "dst_id": n.entity_id, "kind": "attached"} for n in rows]
    kept, pruned = _filter_cleared(rows, edges, _user(ClearanceScope.READ_CLASSIFIED.value))
    assert len(kept) == 2
    assert len(pruned) == 2
