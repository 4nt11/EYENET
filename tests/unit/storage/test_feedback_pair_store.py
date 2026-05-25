"""SQLiteFeedbackPairStore — CRUD + idempotency + ground_truth validation."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from eyenet.contracts.attribution import LinkageRow
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


async def _propose(storage: BaseRepository, a: UUID, b: UUID) -> LinkageRow:
    row = await storage.insert_proposed_linkage(a, b, "t", 0.5, {})
    assert isinstance(row, LinkageRow)
    return row


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(data_dir=Path(tempfile.mkdtemp()))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_inserts_and_orders_pair(storage: BaseRepository) -> None:
    a, b = sorted([uuid4(), uuid4()])
    linkage = await _propose(storage, a, b)
    now = datetime.now(tz=UTC)
    row = await storage.record_feedback_pair(
        linkage_id=linkage.id,
        actor_a=b,  # swapped — store must reorder
        actor_b=a,
        ground_truth="same",
        decided_by="op",
        decided_at=now,
    )
    assert row.actor_a_id == a
    assert row.actor_b_id == b
    assert row.ground_truth == "same"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_idempotent_on_linkage_id_overwrites(storage: BaseRepository) -> None:
    a, b = sorted([uuid4(), uuid4()])
    linkage = await _propose(storage, a, b)
    now = datetime.now(tz=UTC)

    await storage.record_feedback_pair(
        linkage_id=linkage.id,
        actor_a=a,
        actor_b=b,
        ground_truth="same",
        decided_by="op1",
        decided_at=now,
    )
    await storage.record_feedback_pair(
        linkage_id=linkage.id,
        actor_a=a,
        actor_b=b,
        ground_truth="diff",
        decided_by="op2",
        decided_at=now,
        notes="override",
    )
    fetched = await storage.get_feedback_pair(linkage.id)
    assert fetched is not None
    assert fetched.ground_truth == "diff"
    assert fetched.decided_by == "op2"
    assert fetched.notes == "override"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_ground_truth_raises(storage: BaseRepository) -> None:
    a, b = sorted([uuid4(), uuid4()])
    linkage = await _propose(storage, a, b)
    with pytest.raises(ValueError, match="ground_truth must be one of"):
        await storage.record_feedback_pair(
            linkage_id=linkage.id,
            actor_a=a,
            actor_b=b,
            ground_truth="maybe",
            decided_by="op",
            decided_at=datetime.now(tz=UTC),
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_all_pairs_returns_recorded_truth(storage: BaseRepository) -> None:
    now = datetime.now(tz=UTC)
    truths: list[str] = []
    for _ in range(3):
        a, b = sorted([uuid4(), uuid4()])
        linkage = await _propose(storage, a, b)
        await storage.record_feedback_pair(
            linkage_id=linkage.id,
            actor_a=a,
            actor_b=b,
            ground_truth="same",
            decided_by="op",
            decided_at=now,
        )
        truths.append("same")
    pairs = await storage.all_feedback_pairs()
    assert len(pairs) == 3
    assert all(gt == "same" for _, _, gt in pairs)
    # Ordered-pair invariant
    for x, y, _ in pairs:
        assert x < y
