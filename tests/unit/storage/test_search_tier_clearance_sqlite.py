# SPDX-License-Identifier: AGPL-3.0-or-later
"""Global-search clearance gate — a tiered document must not leak through the search box.

Documents ARE indexed into search_document (title + extracted body), so without a tier
filter an uncleared caller could full-text search a classified document. search_global +
its count + its facets honour ``exclude_tiers``; untiered entities sit at 'normal' and
are never excluded. SQLite-impl probe (the FTS predicate seam), same filter on Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.contracts.enums import SensitivityTier
from eyenet.search_indexer import haystack
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 10, 18, tzinfo=UTC)


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> BaseRepository:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    return get_repository(in_memory=True)


async def _index(storage: BaseRepository, entity_type: str, title: str, **extra: object) -> None:
    await storage.put_search_document(
        entity_type=entity_type,
        entity_id=uuid4(),
        title=title,
        haystack=title,
        updated_at=_NOW,
        **extra,
    )


async def test_restricted_document_hidden_from_uncleared_search(storage: BaseRepository) -> None:
    await _index(storage, "document", "secret dump", tier="restricted")
    await _index(storage, "actor", "secret agent")  # untiered -> tier defaults to 'normal'

    # uncleared: both restricted + classified excluded -> only the actor comes back
    cleared_out = await storage.search_global(
        "secret", exclude_tiers=["restricted", "classified"], limit=10
    )
    assert {r.entity_type for r in cleared_out} == {"actor"}
    # count + facets agree: the hidden document is not even counted
    assert (
        await storage.count_search_global("secret", exclude_tiers=["restricted", "classified"]) == 1
    )
    facets = await storage.search_global_facets(
        "secret", exclude_tiers=["restricted", "classified"]
    )
    assert "document" not in facets["by_type"]

    # cleared (no exclusion) -> the document shows
    all_out = await storage.search_global("secret", limit=10)
    assert {r.entity_type for r in all_out} == {"actor", "document"}
    await storage.close()


def test_document_doc_stamps_effective_tier() -> None:
    # operator override wins over the classifier; stamped as column AND in fields (graph).
    from eyenet.models import DocumentTable

    doc = DocumentTable(
        sha256="a" * 64,
        mime="application/pdf",
        size_bytes=1,
        storage_uri="/x",
        uploaded_at=_NOW,
        ingested_at=_NOW,
        classifier_tier=SensitivityTier.NORMAL,
        operator_tier_override=SensitivityTier.CLASSIFIED,
    )
    payload = haystack.document_doc(doc)
    assert payload["tier"] == "classified"
    assert payload["fields"]["tier"] == "classified"
