"""Unit tests for SQLiteObservationStore."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts._base import _new_uuid7
from eyenet.contracts.enums import ValueKind
from eyenet.contracts.observation import ObservationRow
from eyenet.storage.engines import StoreName, create_all_for, open_in_memory_engine
from eyenet.storage.observations import SQLiteObservationStore

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
    engine = open_in_memory_engine()
    create_all_for(StoreName.MAIN, engine)
    return SQLiteObservationStore(engine)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_put_and_latest(store: SQLiteObservationStore) -> None:
    row = _row(value_numeric=0.72)
    await store.put(row)
    results = await store.latest(_ACTOR, "lexical.vocabulary_richness", limit=1)
    assert len(results) == 1
    from eyenet.models import ObservationTable

    obs = results[0]
    assert isinstance(obs, ObservationTable)
    assert obs.value_numeric == pytest.approx(0.72)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_latest_returns_most_recent(store: SQLiteObservationStore) -> None:
    await store.put(_row(value_numeric=0.4))
    await store.put(_row(value_numeric=0.8))
    results = await store.latest(_ACTOR, "lexical.vocabulary_richness", limit=1)
    assert len(results) == 1
    from eyenet.models import ObservationTable

    obs = results[0]
    assert isinstance(obs, ObservationTable)
    assert obs.value_numeric == pytest.approx(0.8)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_by_evidence_and_primitive_found(store: SQLiteObservationStore) -> None:
    row = _row(evidence_ref="telegram:-100:42", primitive="lexical.vocabulary_richness")
    await store.put(row)
    result = await store.by_evidence_and_primitive(
        "telegram:-100:42", "lexical.vocabulary_richness"
    )
    assert result is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_by_evidence_and_primitive_not_found(store: SQLiteObservationStore) -> None:
    result = await store.by_evidence_and_primitive("nonexistent:ref", "lexical.vocabulary_richness")
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_latest_empty_returns_empty_list(store: SQLiteObservationStore) -> None:
    results = await store.latest(_ACTOR, "stylometric.character_ngram_simhash", limit=5)
    assert results == []
