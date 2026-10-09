"""Unit tests for the circadian backfill orchestration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from eyenet.sensor.backfill import run_circadian_backfill
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from tests._seed import seed_telegram_fixture

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 10, 5, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _records(actor_key: str, n: int) -> list[dict[str, object]]:
    base = datetime(2026, 9, 7, tzinfo=UTC)  # Monday
    return [
        {
            "actor_key": actor_key,
            "platform_msgid": f"{actor_key}-{i}",
            "body": f"m{i}",
            "sent_at_source": (base + timedelta(days=i % 5, hours=14 + (i % 6))).isoformat(),
        }
        for i in range(n)
    ]


async def _actor_id(storage: BaseRepository, actor_key: str):
    _s, _g, actors = await seed_telegram_fixture(storage, _records(actor_key, 40), _NOW)
    return actors[actor_key]


@pytest.mark.asyncio
async def test_backfill_one_actor_writes_circadian(storage: BaseRepository) -> None:
    aid = await _actor_id(storage, "k1")
    res = await run_circadian_backfill(storage, actor_id=aid)
    assert res.actors_processed == 1
    # hour + dow + joint + quiet_span (40 msgs / >=2 days clears the gate) = 4
    assert res.observations_written == 4
    hist = await storage.latest_observations(aid, "circadian.hour_histogram", limit=1)
    assert hist


@pytest.mark.asyncio
async def test_backfill_is_idempotent(storage: BaseRepository) -> None:
    aid = await _actor_id(storage, "k1")
    first = await run_circadian_backfill(storage, actor_id=aid)
    assert first.actors_processed == 1
    # Second run skips the already-backfilled actor (observations append, so this
    # guard is what prevents duplicate rows).
    second = await run_circadian_backfill(storage, actor_id=aid)
    assert second.actors_processed == 0
    assert second.actors_skipped == 1
    assert second.observations_written == 0
    # force overrides the skip.
    forced = await run_circadian_backfill(storage, actor_id=aid, force=True)
    assert forced.actors_processed == 1


@pytest.mark.asyncio
async def test_backfill_all_sweeps_every_actor(storage: BaseRepository) -> None:
    _s, _g, actors = await seed_telegram_fixture(
        storage,
        _records("a", 40) + _records("b", 40),
        _NOW,
    )
    res = await run_circadian_backfill(storage, all_actors=True)
    assert res.actors_processed == len(actors)
    assert res.observations_written == 4 * len(actors)


@pytest.mark.asyncio
async def test_requires_a_target(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="actor_id"):
        await run_circadian_backfill(storage)
