# SPDX-License-Identifier: AGPL-3.0-or-later
"""list_personas / count_personas (PersonasMixin, browse list).

Types against BaseRepository + constructs via get_repository per Rule 2
([[feedback_use_basereo_abstraction_in_tests]]).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def test_list_and_count(storage: BaseRepository) -> None:
    await storage.merge_actors_into_persona(uuid4(), uuid4())
    await storage.merge_actors_into_persona(uuid4(), uuid4())
    rows = await storage.list_personas(limit=50, offset=0)
    assert len(rows) == 2
    assert await storage.count_personas() == 2


async def test_list_empty(storage: BaseRepository) -> None:
    assert await storage.list_personas(limit=50, offset=0) == []
    assert await storage.count_personas() == 0


async def test_list_paging(storage: BaseRepository) -> None:
    for _ in range(3):
        await storage.merge_actors_into_persona(uuid4(), uuid4())
    first = await storage.list_personas(limit=2, offset=0)
    second = await storage.list_personas(limit=2, offset=2)
    assert len(first) == 2
    assert len(second) == 1
