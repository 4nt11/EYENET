"""Unit tests for SQLitePersonaStore — all four merge cases + split."""

from __future__ import annotations

from uuid import UUID

import pytest

from eyenet.contracts.attribution import PersonaRow
from eyenet.storage.engines import StoreName, create_all_for, open_in_memory_engine
from eyenet.storage.personas import SQLitePersonaStore

_A = UUID("00000000-0000-0000-0000-000000000001")
_B = UUID("00000000-0000-0000-0000-000000000002")
_C = UUID("00000000-0000-0000-0000-000000000003")
_D = UUID("00000000-0000-0000-0000-000000000004")
_LID = UUID("00000000-0000-0000-0000-000000000099")
_LID2 = UUID("00000000-0000-0000-0000-000000000098")


@pytest.fixture
def store() -> SQLitePersonaStore:
    engine = open_in_memory_engine()
    create_all_for(StoreName.MAIN, engine)
    # Seed linkage rows so FK constraints on via_linkage_id are satisfied
    from datetime import UTC, datetime

    from sqlmodel import Session

    import eyenet.models  # noqa: F401
    from eyenet.contracts.enums import LinkageState
    from eyenet.models.linkage import LinkageTable

    now = datetime(2026, 5, 20, tzinfo=UTC)
    with Session(engine) as session:
        session.add(
            LinkageTable(
                id=_LID,
                actor_a_id=_A,
                actor_b_id=_B,
                state=LinkageState.PROPOSED,
                method="m",
                score=0.5,
                evidence={},
                proposed_at=now,
            )
        )
        session.add(
            LinkageTable(
                id=_LID2,
                actor_a_id=_A,
                actor_b_id=_C,
                state=LinkageState.PROPOSED,
                method="m",
                score=0.5,
                evidence={},
                proposed_at=now,
            )
        )
        session.commit()
    return SQLitePersonaStore(engine)


# --- Case 1: neither actor has a persona ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_merge_case1_creates_new_persona(store: SQLitePersonaStore) -> None:
    persona = await store.merge_actors(_A, _B, via_linkage_id=_LID)
    assert isinstance(persona, PersonaRow)
    assert set(persona.member_actor_ids) == {_A, _B}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_merge_case1_membership_reverse_index(store: SQLitePersonaStore) -> None:
    persona = await store.merge_actors(_A, _B, via_linkage_id=_LID)
    pa = await store.persona_for_actor(_A)
    pb = await store.persona_for_actor(_B)
    assert pa is not None
    assert pa.id == persona.id
    assert pb is not None
    assert pb.id == persona.id


# --- Case 2: one actor has a persona, other does not ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_merge_case2a_adds_actor_to_existing(store: SQLitePersonaStore) -> None:
    existing = await store.merge_actors(_A, _B, via_linkage_id=_LID)
    updated = await store.merge_actors(_A, _C, via_linkage_id=_LID2)
    assert updated.id == existing.id
    assert set(updated.member_actor_ids) == {_A, _B, _C}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_merge_case2b_adds_actor_to_existing_reversed(store: SQLitePersonaStore) -> None:
    existing = await store.merge_actors(_A, _B, via_linkage_id=_LID)
    updated = await store.merge_actors(_C, _A, via_linkage_id=_LID2)
    assert updated.id == existing.id
    assert _C in updated.member_actor_ids


# --- Case 3: both actors already in the same persona ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_merge_case3_same_persona_is_noop(store: SQLitePersonaStore) -> None:
    existing = await store.merge_actors(_A, _B, via_linkage_id=_LID)
    again = await store.merge_actors(_A, _B, via_linkage_id=_LID2)
    assert again.id == existing.id
    assert len(again.member_actor_ids) == 2


# --- Case 4: both actors in different personas ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_merge_case4_merges_two_clusters(store: SQLitePersonaStore) -> None:
    pa = await store.merge_actors(_A, _B, via_linkage_id=_LID)
    pb = await store.merge_actors(_C, _D, via_linkage_id=_LID2)
    assert pa.id != pb.id

    merged = await store.merge_actors(_A, _C, via_linkage_id=_LID)
    assert set(merged.member_actor_ids) == {_A, _B, _C, _D}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_merge_case4_absorbed_persona_deleted(store: SQLitePersonaStore) -> None:
    await store.merge_actors(_A, _B, via_linkage_id=_LID)
    await store.merge_actors(_C, _D, via_linkage_id=_LID2)
    merged = await store.merge_actors(_A, _C, via_linkage_id=_LID)

    all_personas = await store.all_personas()
    ids = {p.id for p in all_personas}
    assert merged.id in ids
    # Exactly one of the two originals was absorbed and deleted
    assert len(ids) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_merge_case4_reverse_membership_updated(store: SQLitePersonaStore) -> None:
    await store.merge_actors(_A, _B, via_linkage_id=_LID)
    await store.merge_actors(_C, _D, via_linkage_id=_LID2)
    merged = await store.merge_actors(_A, _C, via_linkage_id=_LID)

    for actor in (_A, _B, _C, _D):
        persona = await store.persona_for_actor(actor)
        assert persona is not None
        assert persona.id == merged.id


# --- Split ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_split_removes_actor_from_persona(store: SQLitePersonaStore) -> None:
    await store.merge_actors(_A, _B, via_linkage_id=_LID)
    await store.split_actor(_B)
    persona_a = await store.persona_for_actor(_A)
    persona_b = await store.persona_for_actor(_B)
    assert persona_b is None
    if persona_a is not None:
        assert _B not in persona_a.member_actor_ids


@pytest.mark.unit
@pytest.mark.asyncio
async def test_split_actor_not_in_persona_is_noop(store: SQLitePersonaStore) -> None:
    result = await store.split_actor(_A)
    assert result is None


# --- Read helpers ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_persona_returns_row(store: SQLitePersonaStore) -> None:
    created = await store.merge_actors(_A, _B, via_linkage_id=_LID)
    fetched = await store.get_persona(created.id)
    assert fetched is not None
    assert fetched.id == created.id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_persona_returns_none_for_unknown(store: SQLitePersonaStore) -> None:
    result = await store.get_persona(UUID("00000000-0000-0000-0000-999999999999"))
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_members_returns_actor_ids(store: SQLitePersonaStore) -> None:
    persona = await store.merge_actors(_A, _B, via_linkage_id=_LID)
    members = await store.members(persona.id)
    assert set(members) == {_A, _B}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_all_personas_empty_initially(store: SQLitePersonaStore) -> None:
    result = await store.all_personas()
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persona_for_actor_returns_none_initially(store: SQLitePersonaStore) -> None:
    result = await store.persona_for_actor(_A)
    assert result is None
