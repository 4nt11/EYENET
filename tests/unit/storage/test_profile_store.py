"""Unit tests for SQLiteProfileStore — get_current, upsert_current, history."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from eyenet.contracts._base import _new_uuid7
from eyenet.contracts.attribution import ProfileRow
from eyenet.storage.engines import StoreName, create_all_for, open_in_memory_engine
from eyenet.storage.profiles import SQLiteProfileStore

_ACTOR = UUID("00000000-0000-0000-0000-000000000001")
_NOW = datetime(2026, 5, 1, tzinfo=UTC)


def _profile(actor_id: UUID, version: int, mattr: float = 0.5) -> ProfileRow:
    return ProfileRow(
        id=_new_uuid7(),
        actor_id=actor_id,
        version=version,
        is_current=False,
        role_signal=None,
        role_confidence=0.0,
        lexical_summary={
            "mattr": {
                "value": mattr,
                "last_observation_id": "x",
                "derived_from_observation_count": 1,
            }
        },
        derived_at=_NOW,
        derived_from_observation_count=version,
    )


@pytest.fixture
def store() -> SQLiteProfileStore:
    engine = open_in_memory_engine()
    create_all_for(StoreName.PROFILES, engine)
    return SQLiteProfileStore(engine)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_current_returns_none_when_empty(store: SQLiteProfileStore) -> None:
    result = await store.get_current(_ACTOR)
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_current_sets_is_current(store: SQLiteProfileStore) -> None:
    row = _profile(_ACTOR, version=1)
    await store.upsert_current(row)
    current = await store.get_current(_ACTOR)
    assert current is not None
    from eyenet.models import ProfileTable

    assert isinstance(current, ProfileTable)
    assert current.is_current is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_current_demotes_previous(store: SQLiteProfileStore) -> None:
    row1 = _profile(_ACTOR, version=1, mattr=0.4)
    row2 = _profile(_ACTOR, version=2, mattr=0.6)
    await store.upsert_current(row1)
    await store.upsert_current(row2)

    current = await store.get_current(_ACTOR)
    assert current is not None
    assert cast("ProfileRow", current).version == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_history_returns_ordered_versions(store: SQLiteProfileStore) -> None:
    for v in [1, 2, 3]:
        await store.upsert_current(_profile(_ACTOR, version=v))
    history = await store.history(_ACTOR)
    assert len(history) == 3

    versions = [cast("ProfileRow", row).version for row in history]
    assert versions == [1, 2, 3]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_only_one_current_per_actor(store: SQLiteProfileStore) -> None:
    from sqlmodel import Session, col, select

    from eyenet.models import ProfileTable

    for v in [1, 2, 3]:
        await store.upsert_current(_profile(_ACTOR, version=v))

    engine = store._engine
    with Session(engine) as session:
        currents = list(
            session.exec(
                select(ProfileTable)
                .where(ProfileTable.actor_id == _ACTOR)
                .where(col(ProfileTable.is_current).is_(True))
            )
        )
    assert len(currents) == 1
    assert currents[0].version == 3
