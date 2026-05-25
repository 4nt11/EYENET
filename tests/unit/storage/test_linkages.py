"""Unit tests for SQLiteLinkageStore — state machine and idempotency."""

from __future__ import annotations

from typing import cast
from uuid import UUID

import pytest

from eyenet.contracts.attribution import LinkageRow
from eyenet.contracts.enums import LinkageState
from eyenet.storage.repository import BaseRepository
from eyenet.storage.factory import get_repository

_A = UUID("00000000-0000-0000-0000-000000000001")
_B = UUID("00000000-0000-0000-0000-000000000002")
_C = UUID("00000000-0000-0000-0000-000000000003")


@pytest.fixture
def store() -> SQLiteLinkageStore:
    storage = get_repository(in_memory=True)
    return storage
    return storage


@pytest.mark.unit
@pytest.mark.asyncio
async def test_insert_proposed_creates_row(store: BaseRepository) -> None:
    row = await store.insert_proposed_linkage(
        _A, _B, method="function_word_simhash_hamming", score=0.9, evidence={}
    )
    assert isinstance(row, LinkageRow)
    assert row.state == LinkageState.PROPOSED
    assert row.actor_a_id < row.actor_b_id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_insert_proposed_sorts_pair(store: BaseRepository) -> None:
    row = await store.insert_proposed_linkage(_B, _A, method="m", score=0.5, evidence={})
    assert row.actor_a_id == _A
    assert row.actor_b_id == _B


@pytest.mark.unit
@pytest.mark.asyncio
async def test_insert_proposed_idempotent_same_pair_and_method(store: BaseRepository) -> None:
    r1 = await store.insert_proposed_linkage(_A, _B, method="m", score=0.5, evidence={})
    r2 = await store.insert_proposed_linkage(_A, _B, method="m", score=0.9, evidence={})
    assert r1.id == r2.id
    assert r2.score == pytest.approx(0.9)  # updates to higher score


@pytest.mark.unit
@pytest.mark.asyncio
async def test_insert_proposed_different_methods_create_different_rows(
    store: BaseRepository,
) -> None:
    r1 = await store.insert_proposed_linkage(_A, _B, method="m1", score=0.5, evidence={})
    r2 = await store.insert_proposed_linkage(_A, _B, method="m2", score=0.7, evidence={})
    assert r1.id != r2.id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_insert_proposed_honors_passed_linkage_id(
    store: BaseRepository,
) -> None:
    """Bus envelope's linkage_id must equal the DB row id. The whole
    Verifier-over-the-wire path depends on this — M8 debugged it on
    2026-05-24. Pin it so a future refactor cannot silently revert."""
    forced = UUID("00000000-0000-0000-0000-0000000000aa")
    row = await store.insert_proposed_linkage(_A, _B, method="m", score=0.5, evidence={}, linkage_id=forced)
    assert row.id == forced
    fetched = await store.get_linkage(forced)
    assert fetched is not None
    assert fetched.id == forced


@pytest.mark.unit
@pytest.mark.asyncio
async def test_insert_proposed_ignores_linkage_id_on_idempotent_match(
    store: BaseRepository,
) -> None:
    """Per contracts/storage.py docstring: passed linkage_id is *ignored*
    when an existing PROPOSED row matches (pair, method). The returned
    row keeps its original id."""
    r1 = await store.insert_proposed_linkage(_A, _B, method="m", score=0.5, evidence={})
    different_id = UUID("00000000-0000-0000-0000-0000000000bb")
    assert r1.id != different_id
    r2 = await store.insert_proposed_linkage(
        _A, _B, method="m", score=0.9, evidence={}, linkage_id=different_id
    )
    assert r2.id == r1.id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transition_proposed_to_suspected(store: BaseRepository) -> None:
    row = await store.insert_proposed_linkage(_A, _B, method="m", score=0.5, evidence={})
    updated = await store.transition_linkage(row.id, LinkageState.SUSPECTED, decided_by="anti")
    assert updated.state == LinkageState.SUSPECTED
    assert updated.decided_by == "anti"
    assert updated.decided_at is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transition_proposed_to_confirmed(store: BaseRepository) -> None:
    row = await store.insert_proposed_linkage(_A, _B, method="m", score=0.5, evidence={})
    updated = await store.transition_linkage(row.id, LinkageState.CONFIRMED, decided_by="anti")
    assert updated.state == LinkageState.CONFIRMED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transition_proposed_to_rejected(store: BaseRepository) -> None:
    row = await store.insert_proposed_linkage(_A, _B, method="m", score=0.5, evidence={})
    updated = await store.transition_linkage(row.id, LinkageState.REJECTED, decided_by="anti")
    assert updated.state == LinkageState.REJECTED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transition_suspected_to_confirmed(store: BaseRepository) -> None:
    row = await store.insert_proposed_linkage(_A, _B, method="m", score=0.5, evidence={})
    row = await store.transition_linkage(row.id, LinkageState.SUSPECTED, decided_by="anti")
    updated = await store.transition_linkage(row.id, LinkageState.CONFIRMED, decided_by="anti")
    assert updated.state == LinkageState.CONFIRMED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transition_suspected_to_rejected(store: BaseRepository) -> None:
    row = await store.insert_proposed_linkage(_A, _B, method="m", score=0.5, evidence={})
    row = await store.transition_linkage(row.id, LinkageState.SUSPECTED, decided_by="anti")
    updated = await store.transition_linkage(row.id, LinkageState.REJECTED, decided_by="anti")
    assert updated.state == LinkageState.REJECTED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transition_confirmed_is_terminal(store: BaseRepository) -> None:
    row = await store.insert_proposed_linkage(_A, _B, method="m", score=0.5, evidence={})
    row = await store.transition_linkage(row.id, LinkageState.CONFIRMED, decided_by="anti")
    with pytest.raises(ValueError, match="cannot transition"):
        await store.transition_linkage(row.id, LinkageState.REJECTED, decided_by="anti")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transition_rejected_is_terminal(store: BaseRepository) -> None:
    row = await store.insert_proposed_linkage(_A, _B, method="m", score=0.5, evidence={})
    row = await store.transition_linkage(row.id, LinkageState.REJECTED, decided_by="anti")
    with pytest.raises(ValueError, match="cannot transition"):
        await store.transition_linkage(row.id, LinkageState.SUSPECTED, decided_by="anti")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transition_proposed_to_suspected_back_to_proposed_illegal(
    store: BaseRepository,
) -> None:
    row = await store.insert_proposed_linkage(_A, _B, method="m", score=0.5, evidence={})
    row = await store.transition_linkage(row.id, LinkageState.SUSPECTED, decided_by="anti")
    with pytest.raises(ValueError, match="cannot transition"):
        await store.transition_linkage(row.id, LinkageState.PROPOSED, decided_by="anti")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transition_not_found_raises(store: BaseRepository) -> None:
    fake_id = UUID("00000000-0000-0000-0000-000000000099")
    with pytest.raises(ValueError, match="not found"):
        await store.transition_linkage(fake_id, LinkageState.CONFIRMED, decided_by="anti")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_returns_row(store: BaseRepository) -> None:
    row = await store.insert_proposed_linkage(_A, _B, method="m", score=0.5, evidence={})
    fetched = await store.get_linkage(row.id)
    assert fetched is not None
    assert fetched.id == row.id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_returns_none_for_missing(store: BaseRepository) -> None:
    result = await store.get_linkage(UUID("00000000-0000-0000-0000-000000000099"))
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_linkages_returns_all(store: BaseRepository) -> None:
    await store.insert_proposed_linkage(_A, _B, method="m", score=0.5, evidence={})
    await store.insert_proposed_linkage(_A, _C, method="m", score=0.5, evidence={})
    rows = await store.list_linkages()
    assert len(rows) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_linkages_filters_by_actor(store: BaseRepository) -> None:
    await store.insert_proposed_linkage(_A, _B, method="m", score=0.5, evidence={})
    await store.insert_proposed_linkage(_B, _C, method="m", score=0.5, evidence={})
    rows = await store.list_linkages(actor_id=_A)
    assert all(
        _A in (cast("LinkageRow", r).actor_a_id, cast("LinkageRow", r).actor_b_id) for r in rows
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_linkages_filters_by_state(store: BaseRepository) -> None:
    r1 = await store.insert_proposed_linkage(_A, _B, method="m", score=0.5, evidence={})
    await store.transition_linkage(r1.id, LinkageState.CONFIRMED, decided_by="anti")
    await store.insert_proposed_linkage(_A, _C, method="m", score=0.5, evidence={})

    confirmed = await store.list_linkages(state=LinkageState.CONFIRMED)
    assert all(cast("LinkageRow", r).state == LinkageState.CONFIRMED for r in confirmed)
    assert len(confirmed) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transition_notes_stored(store: BaseRepository) -> None:
    row = await store.insert_proposed_linkage(_A, _B, method="m", score=0.5, evidence={})
    updated = await store.transition_linkage(
        row.id, LinkageState.SUSPECTED, decided_by="anti", notes="check this"
    )
    assert updated.notes == "check this"
