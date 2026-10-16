# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the saved-graph handlers (/v1/graphs)."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser, ResourceNotFound
from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.graphs.api_create_graph import graphs_create
from eyenet.api.v1.graphs.api_delete_graph import graphs_delete
from eyenet.api.v1.graphs.api_get_graph import graphs_get
from eyenet.api.v1.graphs.api_list_graphs import graphs_list
from eyenet.api.v1.graphs.api_replace_graph_nodes import graphs_replace_nodes
from eyenet.api.v1.graphs.api_update_graph import graphs_update
from eyenet.api.v1.schemas.saved_graphs import (
    CreateGraphRequest,
    NodePlacementIn,
    ReplaceGraphNodesRequest,
    UpdateGraphRequest,
)
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


async def test_full_roundtrip(storage: BaseRepository, mkuser: Callable[..., CurrentUser]) -> None:
    user = mkuser("write:graph", "read:graph")
    # create
    created = await graphs_create(CreateGraphRequest(name="opA", description="d"), user, storage)
    assert created.name == "opA"
    gid = created.id
    # get (no nodes yet)
    detail = await graphs_get(gid, user, storage)
    assert detail.id == gid
    assert detail.nodes == []
    # list (current user's)
    page = CursorParams(offset=0, limit=50, include_total=False)
    listing = await graphs_list(user, storage, page)
    assert [g.id for g in listing.items] == [gid]
    assert listing.estimated_total is None
    # patch
    renamed = await graphs_update(gid, UpdateGraphRequest(name="opA2"), user, storage)
    assert renamed.name == "opA2"
    # replace nodes
    a, b = uuid4(), uuid4()
    det2 = await graphs_replace_nodes(
        gid,
        ReplaceGraphNodesRequest(
            nodes=[
                NodePlacementIn(entity_type="actor", entity_id=a, x=1.0, y=2.0, pinned=True),
                NodePlacementIn(
                    entity_type="artifact",
                    entity_id=b,
                    x=3.0,
                    y=4.0,
                    enrichments_run=["artifact.messages"],
                ),
            ]
        ),
        user,
        storage,
    )
    assert {n.entity_id for n in det2.nodes} == {a, b}
    # delete
    await graphs_delete(gid, user, storage)
    with pytest.raises(ResourceNotFound):
        await graphs_get(gid, user, storage)
    await storage.close()


async def test_list_is_scoped_to_current_user(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    owner = mkuser("write:graph", "read:graph")
    other = mkuser("read:graph")
    await graphs_create(CreateGraphRequest(name="mine"), owner, storage)
    page = CursorParams(offset=0, limit=50, include_total=False)
    assert (await graphs_list(other, storage, page)).items == []
    await storage.close()


async def test_another_users_graph_is_404_not_accessible(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    owner = mkuser("write:graph", "read:graph")
    intruder = mkuser("write:graph", "read:graph")
    created = await graphs_create(CreateGraphRequest(name="secret op"), owner, storage)
    gid = created.id
    # the intruder holds the right scopes but does not own this graph -> 404 everywhere
    with pytest.raises(ResourceNotFound):
        await graphs_get(gid, intruder, storage)
    with pytest.raises(ResourceNotFound):
        await graphs_update(gid, UpdateGraphRequest(name="hijack"), intruder, storage)
    with pytest.raises(ResourceNotFound):
        await graphs_replace_nodes(gid, ReplaceGraphNodesRequest(nodes=[]), intruder, storage)
    with pytest.raises(ResourceNotFound):
        await graphs_delete(gid, intruder, storage)
    # owner still has full access + the graph was never mutated/deleted by the intruder
    assert (await graphs_get(gid, owner, storage)).name == "secret op"
    await storage.close()


async def test_404s(storage: BaseRepository, mkuser: Callable[..., CurrentUser]) -> None:
    user = mkuser("write:graph", "read:graph")
    missing = uuid4()
    with pytest.raises(ResourceNotFound):
        await graphs_get(missing, user, storage)
    with pytest.raises(ResourceNotFound):
        await graphs_update(missing, UpdateGraphRequest(name="x"), user, storage)
    with pytest.raises(ResourceNotFound):
        await graphs_delete(missing, user, storage)
    with pytest.raises(ResourceNotFound):
        await graphs_replace_nodes(missing, ReplaceGraphNodesRequest(nodes=[]), user, storage)
    await storage.close()
