"""Storage tests for CollectorGroupMembership + MessageObservation (M9.C5).

DoD coverage:
- open/close membership lifecycle
- list_active_memberships filters correctly
- was_first_sighting set correctly for first and second observer
- race test via asyncio.gather: exactly one first-sighting across concurrent observers
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.contracts.enums import GroupKind, JoinedVia, SourceKind
from eyenet.contracts.membership import CollectorGroupMembershipRow, MessageObservationRow
from eyenet.models.message import MessageTable
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 5, 25, tzinfo=UTC)
# Fake UUIDs for deeply-chained FKs that SQLite in-memory does not enforce.
_FAKE_COLLECTOR_A = UUID("00000000-0000-0000-0000-000000000001")
_FAKE_COLLECTOR_B = UUID("00000000-0000-0000-0000-000000000002")
_FAKE_ACTOR = UUID("00000000-0000-0000-0000-000000000003")


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _make_source(storage: BaseRepository) -> UUID:
    return await storage.upsert_source(
        kind=SourceKind.TELEGRAM,
        display_name="telegram:test",
        created_at=_NOW,
    )


async def _make_group(storage: BaseRepository, source_id: UUID, name: str) -> UUID:
    return await storage.upsert_group(
        source_id=source_id,
        platform_groupid=name,
        kind=GroupKind.CHANNEL,
        title=name,
        seen_at=_NOW,
    )


async def _make_message(storage: BaseRepository, source_id: UUID, group_id: UUID) -> UUID:
    """Insert a MessageTable row via escape-hatch session and return its id."""
    async with storage.session() as session:
        row = MessageTable(
            source_id=source_id,
            group_id=group_id,
            actor_id=_FAKE_ACTOR,
            platform_msgid="1001",
            evidence_ref=f"telegram:{uuid4().hex}:1001",
            body="test body",
            body_lang="en",
            length_chars=9,
            length_words=2,
            sent_at_source=_NOW,
            ingested_at=_NOW,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


# --- open + close --------------------------------------------------------


@pytest.mark.unit
async def test_open_membership_round_trip(storage: BaseRepository) -> None:
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "grp_a")

    row = await storage.open_membership(
        collector_id=_FAKE_COLLECTOR_A,
        group_id=grp,
        joined_at=_NOW,
        joined_via=JoinedVia.SEED,
    )
    assert isinstance(row, CollectorGroupMembershipRow)
    assert row.collector_id == _FAKE_COLLECTOR_A
    assert row.group_id == grp
    assert row.joined_via is JoinedVia.SEED
    assert row.left_at is None
    assert row.joined_via_candidate_id is None


@pytest.mark.unit
async def test_open_membership_candidate_via(storage: BaseRepository) -> None:
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "grp_a")
    fake_candidate = uuid4()

    row = await storage.open_membership(
        collector_id=_FAKE_COLLECTOR_A,
        group_id=grp,
        joined_at=_NOW,
        joined_via=JoinedVia.CANDIDATE,
        joined_via_candidate_id=fake_candidate,
    )
    assert row.joined_via is JoinedVia.CANDIDATE
    assert row.joined_via_candidate_id == fake_candidate


@pytest.mark.unit
async def test_open_membership_duplicate_active_raises(storage: BaseRepository) -> None:
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "grp_a")

    await storage.open_membership(
        collector_id=_FAKE_COLLECTOR_A,
        group_id=grp,
        joined_at=_NOW,
        joined_via=JoinedVia.SEED,
    )
    with pytest.raises(ValueError, match="already has an active membership"):
        await storage.open_membership(
            collector_id=_FAKE_COLLECTOR_A,
            group_id=grp,
            joined_at=_NOW,
            joined_via=JoinedVia.RESTORED,
        )


@pytest.mark.unit
async def test_close_membership(storage: BaseRepository) -> None:
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "grp_a")

    await storage.open_membership(
        collector_id=_FAKE_COLLECTOR_A,
        group_id=grp,
        joined_at=_NOW,
        joined_via=JoinedVia.SEED,
    )
    closed = await storage.close_membership(
        collector_id=_FAKE_COLLECTOR_A,
        group_id=grp,
        left_at=_NOW,
        left_reason="operator_stop",
    )
    assert closed.left_at is not None
    assert closed.left_reason == "operator_stop"


@pytest.mark.unit
async def test_close_membership_not_active_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="no active membership"):
        await storage.close_membership(
            collector_id=_FAKE_COLLECTOR_A,
            group_id=uuid4(),
            left_at=_NOW,
            left_reason="operator_stop",
        )


@pytest.mark.unit
async def test_rejoin_after_close_allowed(storage: BaseRepository) -> None:
    # Close then re-open — restored join must succeed.
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "grp_a")

    await storage.open_membership(
        collector_id=_FAKE_COLLECTOR_A,
        group_id=grp,
        joined_at=_NOW,
        joined_via=JoinedVia.SEED,
    )
    await storage.close_membership(
        collector_id=_FAKE_COLLECTOR_A,
        group_id=grp,
        left_at=_NOW,
        left_reason="banned",
    )
    second = await storage.open_membership(
        collector_id=_FAKE_COLLECTOR_A,
        group_id=grp,
        joined_at=_NOW,
        joined_via=JoinedVia.RESTORED,
    )
    assert second.joined_via is JoinedVia.RESTORED
    assert second.left_at is None


# --- list_active_memberships ---------------------------------------------


@pytest.mark.unit
async def test_list_active_memberships_excludes_closed(storage: BaseRepository) -> None:
    src = await _make_source(storage)
    grp_a = await _make_group(storage, src, "grp_a")
    grp_b = await _make_group(storage, src, "grp_b")

    await storage.open_membership(
        collector_id=_FAKE_COLLECTOR_A,
        group_id=grp_a,
        joined_at=_NOW,
        joined_via=JoinedVia.SEED,
    )
    await storage.open_membership(
        collector_id=_FAKE_COLLECTOR_A,
        group_id=grp_b,
        joined_at=_NOW,
        joined_via=JoinedVia.SEED,
    )
    await storage.close_membership(
        collector_id=_FAKE_COLLECTOR_A,
        group_id=grp_b,
        left_at=_NOW,
        left_reason="operator_stop",
    )

    active = await storage.list_active_memberships(collector_id=_FAKE_COLLECTOR_A)
    assert len(active) == 1
    assert active[0].group_id == grp_a


@pytest.mark.unit
async def test_list_active_memberships_group_filter(storage: BaseRepository) -> None:
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "shared_grp")

    await storage.open_membership(
        collector_id=_FAKE_COLLECTOR_A,
        group_id=grp,
        joined_at=_NOW,
        joined_via=JoinedVia.SEED,
    )
    await storage.open_membership(
        collector_id=_FAKE_COLLECTOR_B,
        group_id=grp,
        joined_at=_NOW,
        joined_via=JoinedVia.CANDIDATE,
        joined_via_candidate_id=uuid4(),
    )

    by_group = await storage.list_active_memberships(group_id=grp)
    collector_ids = {r.collector_id for r in by_group}
    assert _FAKE_COLLECTOR_A in collector_ids
    assert _FAKE_COLLECTOR_B in collector_ids


# --- record_observation --------------------------------------------------


@pytest.mark.unit
async def test_record_observation_first_sighting(storage: BaseRepository) -> None:
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "grp_a")
    msg_id = await _make_message(storage, src, grp)

    obs = await storage.record_observation(
        message_id=msg_id,
        collector_id=_FAKE_COLLECTOR_A,
        observed_at_ingest=_NOW,
    )
    assert isinstance(obs, MessageObservationRow)
    assert obs.was_first_sighting is True
    assert obs.message_id == msg_id


@pytest.mark.unit
async def test_record_observation_second_sighting_not_first(storage: BaseRepository) -> None:
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "grp_a")
    msg_id = await _make_message(storage, src, grp)

    await storage.record_observation(
        message_id=msg_id,
        collector_id=_FAKE_COLLECTOR_A,
        observed_at_ingest=_NOW,
    )
    obs_b = await storage.record_observation(
        message_id=msg_id,
        collector_id=_FAKE_COLLECTOR_B,
        observed_at_ingest=_NOW,
    )
    assert obs_b.was_first_sighting is False


@pytest.mark.unit
async def test_record_observation_idempotent(storage: BaseRepository) -> None:
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "grp_a")
    msg_id = await _make_message(storage, src, grp)

    obs1 = await storage.record_observation(
        message_id=msg_id,
        collector_id=_FAKE_COLLECTOR_A,
        observed_at_ingest=_NOW,
    )
    obs2 = await storage.record_observation(
        message_id=msg_id,
        collector_id=_FAKE_COLLECTOR_A,
        observed_at_ingest=_NOW,
    )
    # Same (message, collector) pair — same row returned.
    assert obs1.message_id == obs2.message_id
    assert obs1.collector_id == obs2.collector_id
    assert obs1.was_first_sighting == obs2.was_first_sighting


@pytest.mark.unit
async def test_was_first_sighting_race_asyncio_gather(storage: BaseRepository) -> None:
    # DoD: two concurrent record_observation calls for the same message →
    # exactly one gets was_first_sighting=True, the other gets False.
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "grp_a")
    msg_id = await _make_message(storage, src, grp)

    obs_a, obs_b = await asyncio.gather(
        storage.record_observation(
            message_id=msg_id,
            collector_id=_FAKE_COLLECTOR_A,
            observed_at_ingest=_NOW,
        ),
        storage.record_observation(
            message_id=msg_id,
            collector_id=_FAKE_COLLECTOR_B,
            observed_at_ingest=_NOW,
        ),
    )

    first_count = sum(1 for o in (obs_a, obs_b) if o.was_first_sighting)
    assert first_count == 1, (
        f"Expected exactly one first-sighting but got: "
        f"A={obs_a.was_first_sighting}, B={obs_b.was_first_sighting}"
    )
