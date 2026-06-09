"""Storage tests for GroupCandidate + GroupCandidateMention (M9.C4, MODELS §2.20-2.21).

DoD coverage:
- every illegal transition raises ValueError
- mention upsert is idempotent on (candidate_id, evidence_ref)
- depth_from_root materialized correctly across multi-hop chains
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.contracts.candidate import (
    EligibilityInputs,
    GroupCandidateMentionRow,
    GroupCandidateRow,
)
from eyenet.contracts.enums import CandidateState, GroupKind, MentionKind, SourceKind
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 5, 25, tzinfo=UTC)
_OLDER = datetime(2026, 5, 24, tzinfo=UTC)
# Fake UUIDs for deeply-chained FKs that SQLite in-memory does not enforce.
_FAKE_COLLECTOR = UUID("00000000-0000-0000-0000-000000000001")
_FAKE_ACTOR = UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _make_source(storage: BaseRepository, name: str = "SRC") -> UUID:
    return await storage.upsert_source(
        kind=SourceKind.TELEGRAM,
        display_name=f"telegram:{name}",
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


async def _make_actor(storage: BaseRepository, source_id: UUID, key_suffix: str) -> UUID:
    return await storage.upsert_actor(
        source_id=source_id,
        actor_key=f"actor:{'a' * 60}{key_suffix[:4]}",
        platform_userid=key_suffix,
        handle=None,
        display_name=None,
        seen_at=_NOW,
    )


async def _record(
    storage: BaseRepository,
    source_id: UUID,
    group_id: UUID,
    actor_id: UUID,
    *,
    platform_groupid: str = "tg_-100001",
    evidence_ref: str = "telegram:-100000:999",
    depth: int = 1,
    seed_root_id: UUID | None = None,
    mention_kind: MentionKind = MentionKind.USERNAME_MENTION,
    at: datetime = _NOW,
) -> tuple[GroupCandidateRow, GroupCandidateMentionRow]:
    return await storage.record_candidate_mention(
        source_id=source_id,
        platform_groupid=platform_groupid,
        observed_by_collector_id=_FAKE_COLLECTOR,
        observed_in_group_id=group_id,
        seed_root_id=seed_root_id,
        depth_from_root=depth,
        mention_evidence_ref=evidence_ref,
        mention_kind=mention_kind,
        mentioned_at_source=at,
        mentioned_at_ingest=at,
        mentioning_actor_id=actor_id,
    )


# --- create + read -------------------------------------------------------


@pytest.mark.unit
async def test_record_mention_creates_candidate(storage: BaseRepository) -> None:
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "root_grp")
    actor = await _make_actor(storage, src, "u01")

    candidate, mention = await _record(storage, src, grp, actor)

    assert isinstance(candidate, GroupCandidateRow)
    assert candidate.state is CandidateState.DISCOVERED
    assert candidate.source_id == src
    assert candidate.platform_groupid == "tg_-100001"
    assert candidate.score == 0.0
    assert isinstance(mention, GroupCandidateMentionRow)
    assert mention.candidate_id == candidate.id
    assert mention.depth_from_root == 1


@pytest.mark.unit
async def test_get_candidate_returns_none_for_unknown(storage: BaseRepository) -> None:
    assert await storage.get_candidate(uuid4()) is None


@pytest.mark.unit
async def test_same_source_platform_reuses_candidate(storage: BaseRepository) -> None:
    # Two separate evidence refs for the same (source, platform_groupid) share
    # one candidate row with accumulating mentions.
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "root_grp")
    actor = await _make_actor(storage, src, "u01")

    cand1, _ = await _record(storage, src, grp, actor, evidence_ref="tg:1:1")
    cand2, _ = await _record(storage, src, grp, actor, evidence_ref="tg:1:2")

    assert cand1.id == cand2.id


# --- idempotency ---------------------------------------------------------


@pytest.mark.unit
async def test_record_mention_idempotent_on_evidence_ref(storage: BaseRepository) -> None:
    # Same evidence_ref twice → same mention row returned, no duplicate.
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "root_grp")
    actor = await _make_actor(storage, src, "u01")

    _, mention1 = await _record(storage, src, grp, actor, evidence_ref="tg:1:999")
    _, mention2 = await _record(storage, src, grp, actor, evidence_ref="tg:1:999")

    assert mention1.id == mention2.id


# --- last_observed_at_ingest update ---------------------------------------


@pytest.mark.unit
async def test_record_mention_bumps_last_observed(storage: BaseRepository) -> None:
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "root_grp")
    actor = await _make_actor(storage, src, "u01")

    cand_first, _ = await _record(storage, src, grp, actor, evidence_ref="tg:1:1", at=_OLDER)
    assert cand_first.last_observed_at_ingest == _OLDER

    cand_second, _ = await _record(storage, src, grp, actor, evidence_ref="tg:1:2", at=_NOW)
    assert cand_second.id == cand_first.id
    assert cand_second.last_observed_at_ingest == _NOW


# --- list_queued_candidates ----------------------------------------------


@pytest.mark.unit
async def test_list_queued_candidates_returns_only_queued(storage: BaseRepository) -> None:
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "root_grp")
    actor = await _make_actor(storage, src, "u01")

    cand, _ = await _record(storage, src, grp, actor, platform_groupid="pg_A", evidence_ref="e:A:1")

    # Not yet queued — should be empty.
    assert await storage.list_queued_candidates() == []

    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.QUEUED)
    queued = await storage.list_queued_candidates()
    assert len(queued) == 1
    assert queued[0].id == cand.id


@pytest.mark.unit
async def test_list_queued_candidates_score_desc_order(storage: BaseRepository) -> None:
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "root_grp")
    actor = await _make_actor(storage, src, "u01")

    cand_a, _ = await _record(
        storage, src, grp, actor, platform_groupid="pg_A", evidence_ref="e:A:1"
    )
    cand_b, _ = await _record(
        storage, src, grp, actor, platform_groupid="pg_B", evidence_ref="e:B:1"
    )

    await storage.transition_candidate(candidate_id=cand_a.id, to_state=CandidateState.QUEUED)
    await storage.transition_candidate(candidate_id=cand_b.id, to_state=CandidateState.QUEUED)

    # Manually bump score on B to be higher — go through the DB directly since
    # score update is not exposed as a flat method yet (M9.E1 sensor does it).
    async with storage.session() as session:
        from eyenet.models.candidates import GroupCandidateTable

        row = await session.get(GroupCandidateTable, cand_b.id)
        assert row is not None
        row.score = 99.0
        session.add(row)
        await session.commit()

    queued = await storage.list_queued_candidates()
    assert queued[0].id == cand_b.id
    assert queued[1].id == cand_a.id


@pytest.mark.unit
async def test_list_queued_candidates_source_filter(storage: BaseRepository) -> None:
    src_a = await _make_source(storage, "A")
    src_b = await _make_source(storage, "B")
    grp_a = await _make_group(storage, src_a, "grp_a")
    grp_b = await _make_group(storage, src_b, "grp_b")
    actor_a = await _make_actor(storage, src_a, "ua1")
    actor_b = await _make_actor(storage, src_b, "ub1")

    c_a, _ = await _record(
        storage, src_a, grp_a, actor_a, platform_groupid="pg_A", evidence_ref="ea:1"
    )
    c_b, _ = await _record(
        storage, src_b, grp_b, actor_b, platform_groupid="pg_B", evidence_ref="eb:1"
    )

    await storage.transition_candidate(candidate_id=c_a.id, to_state=CandidateState.QUEUED)
    await storage.transition_candidate(candidate_id=c_b.id, to_state=CandidateState.QUEUED)

    only_a = await storage.list_queued_candidates(source_id=src_a)
    assert all(r.source_id == src_a for r in only_a)
    assert not any(r.source_id == src_b for r in only_a)


# --- state machine -------------------------------------------------------


@pytest.mark.unit
async def test_transition_full_happy_path(storage: BaseRepository) -> None:
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "root_grp")
    actor = await _make_actor(storage, src, "u01")

    cand, _ = await _record(storage, src, grp, actor)

    cand = await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.QUEUED)
    assert cand.state is CandidateState.QUEUED

    cand = await storage.transition_candidate(
        candidate_id=cand.id,
        to_state=CandidateState.APPROVED,
        reviewed_by="operator:admin-001",
        assigned_collector_id=_FAKE_COLLECTOR,
    )
    assert cand.state is CandidateState.APPROVED
    assert cand.assigned_collector_id == _FAKE_COLLECTOR

    cand = await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.JOINING)
    assert cand.state is CandidateState.JOINING

    result_group_id = uuid4()
    cand = await storage.transition_candidate(
        candidate_id=cand.id,
        to_state=CandidateState.JOINED,
        resulting_group_id=result_group_id,
    )
    assert cand.state is CandidateState.JOINED
    assert cand.resulting_group_id == result_group_id


@pytest.mark.unit
async def test_transition_rejection_path(storage: BaseRepository) -> None:
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "root_grp")
    actor = await _make_actor(storage, src, "u01")

    cand, _ = await _record(storage, src, grp, actor)

    cand = await storage.transition_candidate(
        candidate_id=cand.id,
        to_state=CandidateState.REJECTED,
        rejection_reason="Unrelated to investigation scope.",
        reviewed_by="operator:admin-001",
    )
    assert cand.state is CandidateState.REJECTED
    assert cand.rejection_reason == "Unrelated to investigation scope."

    # Rejected → parked (re-evaluation path).
    cand = await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.PARKED)
    assert cand.state is CandidateState.PARKED

    # Parked → approved (fresh operator decision, re-entry).
    cand = await storage.transition_candidate(
        candidate_id=cand.id,
        to_state=CandidateState.APPROVED,
        reviewed_by="operator:admin-001",
        assigned_collector_id=_FAKE_COLLECTOR,
    )
    assert cand.state is CandidateState.APPROVED


@pytest.mark.unit
async def test_transition_failed_to_parked(storage: BaseRepository) -> None:
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "root_grp")
    actor = await _make_actor(storage, src, "u01")

    cand, _ = await _record(storage, src, grp, actor)
    cand = await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.QUEUED)
    cand = await storage.transition_candidate(
        candidate_id=cand.id,
        to_state=CandidateState.APPROVED,
        assigned_collector_id=_FAKE_COLLECTOR,
    )
    cand = await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.JOINING)
    cand = await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.FAILED)
    assert cand.state is CandidateState.FAILED

    cand = await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.PARKED)
    assert cand.state is CandidateState.PARKED


@pytest.mark.unit
async def test_transition_illegal_raises(storage: BaseRepository) -> None:
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "root_grp")
    actor = await _make_actor(storage, src, "u01")

    cand, _ = await _record(storage, src, grp, actor)
    # discovered → joined is not a legal edge.
    with pytest.raises(ValueError, match="illegal candidate transition"):
        await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.JOINED)


async def _drive_to_joining(storage: BaseRepository) -> GroupCandidateRow:
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "root_grp")
    actor = await _make_actor(storage, src, "u01")
    cand, _ = await _record(storage, src, grp, actor)
    cand = await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.QUEUED)
    cand = await storage.transition_candidate(
        candidate_id=cand.id,
        to_state=CandidateState.APPROVED,
        assigned_collector_id=_FAKE_COLLECTOR,
    )
    return await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.JOINING)


@pytest.mark.unit
async def test_transition_joining_to_requested_to_joined(storage: BaseRepository) -> None:
    # M9.E5.5: an approval-gated group accepts a join request, then later
    # admits us → requested → joined.
    cand = await _drive_to_joining(storage)
    cand = await storage.transition_candidate(
        candidate_id=cand.id, to_state=CandidateState.REQUESTED
    )
    assert cand.state is CandidateState.REQUESTED

    result_group_id = uuid4()
    cand = await storage.transition_candidate(
        candidate_id=cand.id,
        to_state=CandidateState.JOINED,
        resulting_group_id=result_group_id,
    )
    assert cand.state is CandidateState.JOINED
    assert cand.resulting_group_id == result_group_id


@pytest.mark.unit
async def test_transition_requested_to_failed(storage: BaseRepository) -> None:
    # A pending request can still be denied/expire → requested → failed.
    cand = await _drive_to_joining(storage)
    cand = await storage.transition_candidate(
        candidate_id=cand.id, to_state=CandidateState.REQUESTED
    )
    cand = await storage.transition_candidate(
        candidate_id=cand.id,
        to_state=CandidateState.FAILED,
        rejection_reason="join request denied",
    )
    assert cand.state is CandidateState.FAILED


@pytest.mark.unit
async def test_transition_requested_to_queued_illegal(storage: BaseRepository) -> None:
    cand = await _drive_to_joining(storage)
    cand = await storage.transition_candidate(
        candidate_id=cand.id, to_state=CandidateState.REQUESTED
    )
    # requested → queued is NOT a legal edge.
    with pytest.raises(ValueError, match="illegal candidate transition"):
        await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.QUEUED)


@pytest.mark.unit
async def test_transition_not_found_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.transition_candidate(candidate_id=uuid4(), to_state=CandidateState.QUEUED)


# --- eligibility inputs --------------------------------------------------


@pytest.mark.unit
async def test_compute_eligibility_min_depth(storage: BaseRepository) -> None:
    # Two mentions from the same collector at different depths — min_depth picks the shallower.
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "root_grp")
    actor = await _make_actor(storage, src, "u01")

    await storage.record_candidate_mention(
        source_id=src,
        platform_groupid="tg_-100999",
        observed_by_collector_id=_FAKE_COLLECTOR,
        observed_in_group_id=grp,
        seed_root_id=grp,
        depth_from_root=1,
        mention_evidence_ref="tg:hop1:1",
        mention_kind=MentionKind.FORWARD_ORIGIN,
        mentioned_at_source=_NOW,
        mentioned_at_ingest=_NOW,
        mentioning_actor_id=actor,
    )
    # Same collector, same candidate, but observed 2 hops deep.
    cand, _ = await storage.record_candidate_mention(
        source_id=src,
        platform_groupid="tg_-100999",
        observed_by_collector_id=_FAKE_COLLECTOR,
        observed_in_group_id=grp,
        seed_root_id=grp,
        depth_from_root=2,
        mention_evidence_ref="tg:hop2:1",
        mention_kind=MentionKind.INVITE_LINK,
        mentioned_at_source=_NOW,
        mentioned_at_ingest=_NOW,
        mentioning_actor_id=actor,
    )

    inputs = await storage.compute_eligibility_inputs(cand.id)
    assert isinstance(inputs, EligibilityInputs)
    assert inputs.candidate.id == cand.id
    assert len(inputs.mentions) == 2
    # Min depth across both mentions for this collector is 1 (not 2).
    assert inputs.min_depth_by_collector[_FAKE_COLLECTOR] == 1


@pytest.mark.unit
async def test_compute_eligibility_two_collectors(storage: BaseRepository) -> None:
    second_collector = UUID("00000000-0000-0000-0000-000000000003")
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "root_grp")
    actor = await _make_actor(storage, src, "u01")

    cand, _ = await storage.record_candidate_mention(
        source_id=src,
        platform_groupid="tg_-100888",
        observed_by_collector_id=_FAKE_COLLECTOR,
        observed_in_group_id=grp,
        seed_root_id=grp,
        depth_from_root=1,
        mention_evidence_ref="tg:c1:1",
        mention_kind=MentionKind.USERNAME_MENTION,
        mentioned_at_source=_NOW,
        mentioned_at_ingest=_NOW,
        mentioning_actor_id=actor,
    )
    await storage.record_candidate_mention(
        source_id=src,
        platform_groupid="tg_-100888",
        observed_by_collector_id=second_collector,
        observed_in_group_id=grp,
        seed_root_id=grp,
        depth_from_root=3,
        mention_evidence_ref="tg:c2:1",
        mention_kind=MentionKind.USERNAME_MENTION,
        mentioned_at_source=_NOW,
        mentioned_at_ingest=_NOW,
        mentioning_actor_id=actor,
    )

    inputs = await storage.compute_eligibility_inputs(cand.id)
    assert inputs.min_depth_by_collector[_FAKE_COLLECTOR] == 1
    assert inputs.min_depth_by_collector[second_collector] == 3


@pytest.mark.unit
async def test_compute_eligibility_not_found_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.compute_eligibility_inputs(uuid4())


# --- depth_from_root materialization ------------------------------------


@pytest.mark.unit
async def test_depth_from_root_preserved(storage: BaseRepository) -> None:
    # Mention at depth 0 (direct seed observation) stores depth correctly.
    src = await _make_source(storage)
    grp = await _make_group(storage, src, "seed_root")
    actor = await _make_actor(storage, src, "u01")

    _, mention = await storage.record_candidate_mention(
        source_id=src,
        platform_groupid="tg_-100111",
        observed_by_collector_id=_FAKE_COLLECTOR,
        observed_in_group_id=grp,
        seed_root_id=grp,
        depth_from_root=0,
        mention_evidence_ref="tg:seed:1",
        mention_kind=MentionKind.BIO_LINK,
        mentioned_at_source=_NOW,
        mentioned_at_ingest=_NOW,
        mentioning_actor_id=actor,
    )
    assert mention.depth_from_root == 0
    assert mention.seed_root_id == grp


# -- requested-candidate queries (M9.E5.6) -----------------------------------


async def _requested_for(
    storage: BaseRepository,
    src: UUID,
    collector_id: UUID,
    *,
    platform_groupid: str,
    evidence_ref: str,
) -> GroupCandidateRow:
    """Drive a fresh candidate JOINING→REQUESTED assigned to ``collector_id``."""
    grp = await _make_group(storage, src, f"g_{evidence_ref}")
    actor = await _make_actor(storage, src, evidence_ref)
    cand, _ = await _record(
        storage, src, grp, actor, platform_groupid=platform_groupid, evidence_ref=evidence_ref
    )
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.QUEUED)
    await storage.transition_candidate(
        candidate_id=cand.id,
        to_state=CandidateState.APPROVED,
        assigned_collector_id=collector_id,
    )
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.JOINING)
    return await storage.transition_candidate(
        candidate_id=cand.id, to_state=CandidateState.REQUESTED
    )


@pytest.mark.unit
async def test_requested_candidates_for_collector_filters_state_and_collector(
    storage: BaseRepository,
) -> None:
    src = await _make_source(storage)
    coll_a = UUID("00000000-0000-0000-0000-0000000000aa")
    coll_b = UUID("00000000-0000-0000-0000-0000000000bb")

    want = await _requested_for(
        storage, src, coll_a, platform_groupid="@wanted", evidence_ref="ev_a"
    )
    # Other collector's REQUESTED candidate — must be excluded.
    await _requested_for(storage, src, coll_b, platform_groupid="@other", evidence_ref="ev_b")
    # Same collector but still JOINING (not REQUESTED) — must be excluded.
    grp = await _make_group(storage, src, "g_joining")
    actor = await _make_actor(storage, src, "ev_c")
    joining, _ = await _record(
        storage, src, grp, actor, platform_groupid="@joining", evidence_ref="ev_c"
    )
    await storage.transition_candidate(candidate_id=joining.id, to_state=CandidateState.QUEUED)
    await storage.transition_candidate(
        candidate_id=joining.id, to_state=CandidateState.APPROVED, assigned_collector_id=coll_a
    )
    await storage.transition_candidate(candidate_id=joining.id, to_state=CandidateState.JOINING)

    rows = await storage.requested_candidates_for_collector(coll_a)
    assert [r.id for r in rows] == [want.id]


@pytest.mark.unit
async def test_requested_candidate_for_group_scoped_by_collector_and_groupid(
    storage: BaseRepository,
) -> None:
    src = await _make_source(storage)
    coll_a = UUID("00000000-0000-0000-0000-0000000000aa")
    coll_b = UUID("00000000-0000-0000-0000-0000000000bb")

    want = await _requested_for(storage, src, coll_a, platform_groupid="@grp", evidence_ref="ev_a")
    # Different collector, same platform_groupid — must NOT cross-match.
    await _requested_for(storage, src, coll_b, platform_groupid="@grp_b", evidence_ref="ev_b")

    hit = await storage.requested_candidate_for_group(collector_id=coll_a, platform_groupid="@grp")
    assert hit is not None
    assert hit.id == want.id

    # Wrong group id for the right collector → no match.
    miss = await storage.requested_candidate_for_group(
        collector_id=coll_a, platform_groupid="@grp_b"
    )
    assert miss is None

    # Right group id but wrong collector → no match (cross-collector isolation).
    cross = await storage.requested_candidate_for_group(
        collector_id=coll_b, platform_groupid="@grp"
    )
    assert cross is None


# -- claim_candidate_transition (Defect 4 — atomic CAS) ----------------------


@pytest.mark.unit
async def test_claim_candidate_transition_winner_updates_state_and_group(
    storage: BaseRepository,
) -> None:
    cand = await _drive_to_joining(storage)
    cand = await storage.transition_candidate(
        candidate_id=cand.id, to_state=CandidateState.REQUESTED
    )
    group_id = uuid4()

    won = await storage.claim_candidate_transition(
        cand.id,
        from_state=CandidateState.REQUESTED,
        to_state=CandidateState.JOINED,
        resulting_group_id=group_id,
    )
    assert won is True
    row = await storage.get_candidate(cand.id)
    assert row.state is CandidateState.JOINED
    assert row.resulting_group_id == group_id


@pytest.mark.unit
async def test_claim_candidate_transition_second_call_loses(
    storage: BaseRepository,
) -> None:
    # The CAS is the idempotency primitive: once the state moved off REQUESTED,
    # a second identical claim finds no matching row → False, no further update.
    cand = await _drive_to_joining(storage)
    cand = await storage.transition_candidate(
        candidate_id=cand.id, to_state=CandidateState.REQUESTED
    )
    first_group = uuid4()
    second_group = uuid4()

    first = await storage.claim_candidate_transition(
        cand.id,
        from_state=CandidateState.REQUESTED,
        to_state=CandidateState.JOINED,
        resulting_group_id=first_group,
    )
    second = await storage.claim_candidate_transition(
        cand.id,
        from_state=CandidateState.REQUESTED,
        to_state=CandidateState.JOINED,
        resulting_group_id=second_group,
    )
    assert first is True
    assert second is False
    row = await storage.get_candidate(cand.id)
    # the loser changed NOTHING — the first winner's group id stands
    assert row.resulting_group_id == first_group


@pytest.mark.unit
async def test_claim_candidate_transition_wrong_from_state_noop(
    storage: BaseRepository,
) -> None:
    # A claim whose from_state doesn't match the live state matches no row and
    # mutates nothing.
    cand = await _drive_to_joining(storage)  # state == JOINING
    won = await storage.claim_candidate_transition(
        cand.id,
        from_state=CandidateState.REQUESTED,  # wrong: candidate is JOINING
        to_state=CandidateState.JOINED,
        resulting_group_id=uuid4(),
    )
    assert won is False
    row = await storage.get_candidate(cand.id)
    assert row.state is CandidateState.JOINING
    assert row.resulting_group_id is None


@pytest.mark.unit
async def test_claim_candidate_transition_missing_candidate_false(
    storage: BaseRepository,
) -> None:
    won = await storage.claim_candidate_transition(
        uuid4(),
        from_state=CandidateState.REQUESTED,
        to_state=CandidateState.JOINED,
    )
    assert won is False
