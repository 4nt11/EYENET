# SPDX-License-Identifier: AGPL-3.0-or-later
"""hydrate_search_documents — batch id -> search_document (saved-graph reload)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def test_hydrate_by_ids(storage: BaseRepository) -> None:
    a, b = uuid4(), uuid4()
    await storage.put_search_document(entity_type="actor", entity_id=a, title="zfo")
    await storage.put_search_document(
        entity_type="artifact", entity_id=b, title="x.onion", kind="onion"
    )
    missing = uuid4()
    rows = await storage.hydrate_search_documents([a, b, missing])
    by_id = {r.entity_id: r for r in rows}
    assert set(by_id) == {a, b}  # the unindexed id is simply absent
    assert by_id[a].title == "zfo"
    assert by_id[b].entity_type == "artifact"
    assert await storage.hydrate_search_documents([]) == []
    await storage.close()
