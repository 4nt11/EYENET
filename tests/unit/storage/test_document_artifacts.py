# SPDX-License-Identifier: AGPL-3.0-or-later
"""document_artifact edge — record + dedup + graph_expand(document, artifacts).

Types against BaseRepository + constructs via get_repository (Rule 2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.contracts.document import DocumentRow
from eyenet.contracts.enums import SensitivityTier
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 5, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _hex64() -> str:
    return uuid4().hex + uuid4().hex


async def _put_document(storage: BaseRepository) -> object:
    return await storage.put_document(
        DocumentRow(
            sha256=_hex64(),
            mime="application/pdf",
            size_bytes=10,
            doc_kind="pdf",
            filename="leak.pdf",
            storage_uri="/data/documents/x.bin",
            extracted_text="visit abc.onion for more",
            uploaded_at=_NOW,
            ingested_at=_NOW,
            classifier_tier=SensitivityTier.NORMAL,
        )
    )


async def test_record_document_artifacts_and_dedup(storage: BaseRepository) -> None:
    doc_id = await _put_document(storage)
    inds = [("onion", "abc.onion", 6), ("onion", "xyz.onion", None)]
    n = await storage.record_document_artifacts(document_id=doc_id, indicators=inds, now=_NOW)
    assert n == 2
    # re-run is idempotent (edge dedupes on (artifact_id, document_id))
    n2 = await storage.record_document_artifacts(document_id=doc_id, indicators=inds, now=_NOW)
    assert n2 == 0
    await storage.close()


async def test_graph_expand_document_to_artifacts(storage: BaseRepository) -> None:
    doc_id = await _put_document(storage)
    # create + index the artifact so it hydrates as a neighbour; record_document_
    # artifacts dedupes on value_hash, so it reuses this same artifact row.
    art_id = await storage.create_operator_artifact(kind="onion", value="abc.onion", now=_NOW)
    await storage.put_search_document(
        entity_type="artifact", entity_id=art_id, title="abc.onion", kind="onion"
    )
    await storage.record_document_artifacts(
        document_id=doc_id, indicators=[("onion", "abc.onion", 0)], now=_NOW
    )
    arts, edges, total, more = await storage.graph_expand(
        src_type="document",
        src_id=doc_id,
        enrichment="artifacts",
        limit=10,
        offset=0,
        want_total=True,
    )
    assert [n.entity_id for n in arts] == [art_id]
    assert edges == [{"src_id": doc_id, "dst_id": art_id, "kind": "contains_artifact"}]
    assert total == 1
    assert more is False
    await storage.close()


async def test_graph_expand_document_unknown_enrichment(storage: BaseRepository) -> None:
    doc_id = await _put_document(storage)
    with pytest.raises(ValueError, match="unknown enrichment"):
        await storage.graph_expand(
            src_type="document",
            src_id=doc_id,
            enrichment="nope",
            limit=1,
            offset=0,
            want_total=False,
        )
    await storage.close()
