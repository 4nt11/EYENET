# SPDX-License-Identifier: AGPL-3.0-or-later
"""list_actors / count_actors (ActorsMixin, unfiltered browse list).

Types against BaseRepository + constructs via get_repository per Rule 2
([[feedback_use_basereo_abstraction_in_tests]]).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from eyenet.contracts.enums import SourceKind
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _seed(storage: BaseRepository, key: str, seen: datetime) -> None:
    source_id = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:test", created_at=_NOW
    )
    await storage.upsert_actor(
        source_id=source_id,
        actor_key=key,
        platform_userid=key[-8:],
        handle=key,
        display_name=None,
        seen_at=seen,
    )


async def test_list_newest_activity_first(storage: BaseRepository) -> None:
    await _seed(storage, "tg:old", _NOW - timedelta(days=2))
    await _seed(storage, "tg:new", _NOW)
    rows = await storage.list_actors(limit=50, offset=0)
    assert len(rows) == 2
    assert rows[0].actor_key == "tg:new"  # type: ignore[attr-defined]
    assert await storage.count_actors() == 2


async def test_list_empty(storage: BaseRepository) -> None:
    assert await storage.list_actors(limit=50, offset=0) == []
    assert await storage.count_actors() == 0


async def test_list_paging(storage: BaseRepository) -> None:
    for i in range(3):
        await _seed(storage, f"tg:a{i}", _NOW - timedelta(hours=i))
    first = await storage.list_actors(limit=2, offset=0)
    second = await storage.list_actors(limit=2, offset=2)
    assert len(first) == 2
    assert len(second) == 1
