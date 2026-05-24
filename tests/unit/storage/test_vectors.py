"""Unit tests for SQLiteVectorIndex — nearest() correctness on known fixtures."""

from __future__ import annotations

from uuid import UUID

import pytest

from eyenet.storage.engines import StoreName, create_all_for, open_in_memory_engine
from eyenet.storage.vectors import SQLiteVectorIndex, _hex_to_int, _int_to_hex

_ACTOR_A = UUID("00000000-0000-0000-0000-000000000001")
_ACTOR_B = UUID("00000000-0000-0000-0000-000000000002")
_ACTOR_C = UUID("00000000-0000-0000-0000-000000000003")
_ACTOR_D = UUID("00000000-0000-0000-0000-000000000004")

_PRIM = "function_word_distribution_top50"

_BASE = "0000000000000000"
_DIST1 = "0000000000000001"  # 1 bit from BASE
_DIST4 = "000000000000000f"  # 4 bits from BASE
_DIST64 = "ffffffffffffffff"  # 64 bits from BASE


@pytest.fixture
def index() -> SQLiteVectorIndex:
    engine = open_in_memory_engine()
    create_all_for(StoreName.MAIN, engine)
    return SQLiteVectorIndex(engine)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_and_nearest_returns_match(index: SQLiteVectorIndex) -> None:
    await index.upsert_simhash(_ACTOR_A, _PRIM, _BASE)
    matches = await index.nearest(_PRIM, _DIST1, max_distance=8)
    assert len(matches) == 1
    assert matches[0].actor_id == _ACTOR_A
    assert matches[0].distance == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nearest_returns_correct_simhash_hex(index: SQLiteVectorIndex) -> None:
    await index.upsert_simhash(_ACTOR_A, _PRIM, _BASE)
    matches = await index.nearest(_PRIM, _DIST1, max_distance=8)
    assert matches[0].simhash_hex == _BASE


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nearest_respects_max_distance(index: SQLiteVectorIndex) -> None:
    await index.upsert_simhash(_ACTOR_A, _PRIM, _BASE)  # distance 0
    await index.upsert_simhash(_ACTOR_B, _PRIM, _DIST1)  # distance 1
    await index.upsert_simhash(_ACTOR_C, _PRIM, _DIST4)  # distance 4
    await index.upsert_simhash(_ACTOR_D, _PRIM, _DIST64)  # distance 64

    matches = await index.nearest(_PRIM, _BASE, max_distance=4)
    actor_ids = {m.actor_id for m in matches}
    assert _ACTOR_A in actor_ids
    assert _ACTOR_B in actor_ids
    assert _ACTOR_C in actor_ids
    assert _ACTOR_D not in actor_ids


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nearest_excludes_specified_actor(index: SQLiteVectorIndex) -> None:
    await index.upsert_simhash(_ACTOR_A, _PRIM, _BASE)
    await index.upsert_simhash(_ACTOR_B, _PRIM, _DIST1)

    matches = await index.nearest(_PRIM, _BASE, max_distance=8, exclude_actor_id=_ACTOR_A)
    actor_ids = {m.actor_id for m in matches}
    assert _ACTOR_A not in actor_ids
    assert _ACTOR_B in actor_ids


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nearest_returns_empty_on_no_data(index: SQLiteVectorIndex) -> None:
    matches = await index.nearest(_PRIM, _BASE, max_distance=8)
    assert matches == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nearest_sorted_by_distance_ascending(index: SQLiteVectorIndex) -> None:
    await index.upsert_simhash(_ACTOR_A, _PRIM, _DIST4)  # distance 4
    await index.upsert_simhash(_ACTOR_B, _PRIM, _DIST1)  # distance 1

    matches = await index.nearest(_PRIM, _BASE, max_distance=8)
    distances = [m.distance for m in matches]
    assert distances == sorted(distances)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_is_idempotent(index: SQLiteVectorIndex) -> None:
    await index.upsert_simhash(_ACTOR_A, _PRIM, _BASE)
    await index.upsert_simhash(_ACTOR_A, _PRIM, _DIST1)  # overwrite
    matches = await index.nearest(_PRIM, _BASE, max_distance=8)
    assert len(matches) == 1
    assert matches[0].simhash_hex == _DIST1  # updated


@pytest.mark.unit
@pytest.mark.asyncio
async def test_different_primitives_are_isolated(index: SQLiteVectorIndex) -> None:
    other_prim = "character_ngram_simhash"
    await index.upsert_simhash(_ACTOR_A, _PRIM, _BASE)
    await index.upsert_simhash(_ACTOR_B, other_prim, _DIST1)

    matches = await index.nearest(_PRIM, _DIST1, max_distance=8)
    assert all(m.actor_id == _ACTOR_A for m in matches)

    matches_other = await index.nearest(other_prim, _DIST1, max_distance=8)
    assert all(m.actor_id == _ACTOR_B for m in matches_other)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nearest_respects_limit(index: SQLiteVectorIndex) -> None:
    actors = [UUID(f"00000000-0000-0000-0000-{i:012d}") for i in range(1, 11)]
    for actor in actors:
        await index.upsert_simhash(actor, _PRIM, _DIST1)

    matches = await index.nearest(_PRIM, _BASE, max_distance=8, limit=3)
    assert len(matches) <= 3


@pytest.mark.unit
def test_hex_to_int_round_trip() -> None:
    for h in ["0000000000000000", "ffffffffffffffff", "deadbeefcafebabe"]:
        assert _int_to_hex(_hex_to_int(h)) == h


@pytest.mark.unit
def test_hex_to_int_handles_high_bit() -> None:
    # ffffffffffffffff = -1 as signed 64-bit
    assert _hex_to_int("ffffffffffffffff") == -1


@pytest.mark.unit
def test_int_to_hex_handles_negative() -> None:
    assert _int_to_hex(-1) == "ffffffffffffffff"
