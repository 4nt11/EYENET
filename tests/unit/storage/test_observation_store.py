"""Unit tests for SQLiteObservationStore."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts._base import _new_uuid7
from eyenet.contracts.enums import ValueKind
from eyenet.contracts.observation import ObservationRow
from eyenet.storage.repository import BaseRepository
from eyenet.storage.factory import get_repository

_ACTOR = UUID("00000000-0000-0000-0000-000000000001")
_TS = datetime(2026, 5, 1, tzinfo=UTC)


def _row(
    actor_id: UUID = _ACTOR,
    primitive: str = "lexical.vocabulary_richness",
    value_numeric: float = 0.5,
    evidence_ref: str = "test:ref:1",
) -> ObservationRow:
    return ObservationRow(
        id=_new_uuid7(),
        actor_id=actor_id,
        primitive_namespace=primitive.split(".", maxsplit=1)[0],
        primitive_name=primitive,
        primitive_version="0.1",
        value_kind=ValueKind.NUMERIC,
        value_numeric=value_numeric,
        evidence_ref=evidence_ref,
        observed_at=_TS,
        sensor_instance="test",
    )


@pytest.fixture
def store() -> SQLiteObservationStore:
    storage = get_repository(in_memory=True)
    return storage
    return storage


@pytest.mark.unit
@pytest.mark.asyncio
async def test_put_and_latest(store: BaseRepository) -> None:
    row = _row(value_numeric=0.72)
    await store.put_observation(row)
    results = await store.latest_observations(_ACTOR, "lexical.vocabulary_richness", limit=1)
    assert len(results) == 1
    from eyenet.models import ObservationTable

    obs = results[0]
    assert isinstance(obs, ObservationTable)
    assert obs.value_numeric == pytest.approx(0.72)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_latest_returns_most_recent(store: BaseRepository) -> None:
    await store.put_observation(_row(value_numeric=0.4))
    await store.put_observation(_row(value_numeric=0.8))
    results = await store.latest_observations(_ACTOR, "lexical.vocabulary_richness", limit=1)
    assert len(results) == 1
    from eyenet.models import ObservationTable

    obs = results[0]
    assert isinstance(obs, ObservationTable)
    assert obs.value_numeric == pytest.approx(0.8)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_by_evidence_and_primitive_found(store: BaseRepository) -> None:
    row = _row(evidence_ref="telegram:-100:42", primitive="lexical.vocabulary_richness")
    await store.put_observation(row)
    result = await store.observation_by_evidence_and_primitive(
        "telegram:-100:42", "lexical.vocabulary_richness"
    )
    assert result is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_by_evidence_and_primitive_not_found(store: BaseRepository) -> None:
    result = await store.observation_by_evidence_and_primitive("nonexistent:ref", "lexical.vocabulary_richness")
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_latest_empty_returns_empty_list(store: BaseRepository) -> None:
    results = await store.latest_observations(_ACTOR, "stylometric.character_ngram_simhash", limit=5)
    assert results == []
