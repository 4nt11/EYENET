# SPDX-License-Identifier: AGPL-3.0-or-later
"""Artifact ``kind`` as a first-class search facet — SQLite-impl probe.

Indexes infrastructure artifacts via the backfill sweep and proves the
InfrastructureKind is filterable (DSL ``artifact.kind == ...``) and faceted
(``by_kind``) through the global-search surface — not just buried in free text.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyenet.contracts.enums import InfrastructureKind
from eyenet.search_indexer.backfill import backfill_search
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 10, 14, tzinfo=UTC)


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> BaseRepository:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    return get_repository(in_memory=True)


async def _seed(storage: BaseRepository) -> None:
    await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.WALLET_BTC,
        value="scamx-btc-wallet",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.EMAIL,
        value="scamx@evil.test",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    await backfill_search(storage)


async def test_kind_is_indexed_and_filterable(storage: BaseRepository) -> None:
    await _seed(storage)
    rows = await storage.search_global("artifact.kind == wallet_btc", limit=50)
    assert len(rows) == 1
    assert rows[0].entity_type == "artifact"
    assert rows[0].kind == "wallet_btc"
    await storage.close()


async def test_by_kind_facet_counts(storage: BaseRepository) -> None:
    await _seed(storage)
    facets = await storage.search_global_facets("scamx")
    assert facets["by_kind"] == {"wallet_btc": 1, "email": 1}
    await storage.close()
