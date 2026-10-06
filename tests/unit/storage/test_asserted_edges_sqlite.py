# SPDX-License-Identifier: AGPL-3.0-or-later
"""AssertedEdgesMixin — operator-mapped graph edges (GLOBAL_SEARCH.md §10.4)."""

from __future__ import annotations

import uuid

import pytest

from eyenet.storage.errors import AssertedEdgeError
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> BaseRepository:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    return get_repository(in_memory=True)


@pytest.mark.asyncio
async def test_assert_list_retract_roundtrip(storage: BaseRepository) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    user = uuid.uuid4()
    edge = await storage.assert_edge(
        src_type="actor", src_id=a, dst_type="artifact", dst_id=b,
        kind="associate", reason="share t.me/zfoleaks", created_by_user_id=user,
        service="test", instance_id="t0",
    )
    edge_id = edge.id  # type: ignore[attr-defined]

    # idempotent on (src,dst,kind)
    again = await storage.assert_edge(
        src_type="actor", src_id=a, dst_type="artifact", dst_id=b,
        kind="associate", reason="share t.me/zfoleaks", created_by_user_id=user,
        service="test", instance_id="t0",
    )
    assert again.id == edge_id  # type: ignore[attr-defined]

    # both endpoints in the node set -> returned
    assert len(await storage.list_asserted_edges_for({a, b})) == 1
    # only one endpoint -> not returned (induced subgraph needs both)
    assert len(await storage.list_asserted_edges_for({a})) == 0

    # audited
    events = {r.event for r in await storage.all_audit()}
    assert "eyenet.audit.graph.edge_asserted" in events

    # retract soft-deletes -> excluded from the active list
    assert await storage.retract_edge(
        edge_id=edge_id, removed_by_user_id=user, reason="wrong", service="test", instance_id="t0"
    )
    assert len(await storage.list_asserted_edges_for({a, b})) == 0
    # retract again -> False (already removed)
    assert not await storage.retract_edge(
        edge_id=edge_id, removed_by_user_id=user, reason="x", service="test", instance_id="t0"
    )
    events2 = {r.event for r in await storage.all_audit()}
    assert "eyenet.audit.graph.edge_retracted" in events2
    await storage.close()


@pytest.mark.asyncio
async def test_assert_rejects_trivial_reason(storage: BaseRepository) -> None:
    with pytest.raises(AssertedEdgeError):
        await storage.assert_edge(
            src_type="actor", src_id=uuid.uuid4(), dst_type="actor", dst_id=uuid.uuid4(),
            kind="associate", reason="x", created_by_user_id=uuid.uuid4(),
            service="test", instance_id="t0",
        )
    await storage.close()
