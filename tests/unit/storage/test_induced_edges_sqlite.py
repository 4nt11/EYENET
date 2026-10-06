# SPDX-License-Identifier: AGPL-3.0-or-later
"""induced_edges — derived edges among search-result nodes (GLOBAL_SEARCH.md §10.3).

Exercises the scoping invariant (an edge appears only when BOTH endpoints are in
the node set) via linkage rows; the other derived edge types use the same clause.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from eyenet.contracts.enums import LinkageState
from eyenet.models.linkage import LinkageTable
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 10, 5, tzinfo=UTC)


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> BaseRepository:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    return get_repository(in_memory=True)


@pytest.mark.asyncio
async def test_induced_edges_scopes_to_node_set(storage: BaseRepository) -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    # the linkage table enforces a canonical ordered pair (actor_a_id < actor_b_id).
    ab_lo, ab_hi = sorted((a, b))
    ac_lo, ac_hi = sorted((a, c))
    async with storage.session() as s:
        s.add(
            LinkageTable(
                actor_a_id=ab_lo, actor_b_id=ab_hi, state=LinkageState.CONFIRMED,
                method="shared_infra", score=0.9, proposed_at=_NOW,
            )
        )
        s.add(
            LinkageTable(
                actor_a_id=ac_lo, actor_b_id=ac_hi, state=LinkageState.PROPOSED,
                method="shared_infra", score=0.5, proposed_at=_NOW,
            )
        )
        await s.commit()

    # a and b are nodes -> the a-b edge is induced; c is NOT a node -> a-c excluded.
    edges = await storage.induced_edges(actor_ids=[a, b], persona_ids=[], artifact_ids=[])
    linked = [e for e in edges if e["kind"] == "linked"]
    assert len(linked) == 1
    e = linked[0]
    assert {e["src_id"], e["dst_id"]} == {a, b}
    assert e["weight"] == 0.9
    assert e["meta"]["state"] == "confirmed"

    # no actor nodes -> no edges
    assert await storage.induced_edges(actor_ids=[], persona_ids=[], artifact_ids=[]) == []
    await storage.close()
