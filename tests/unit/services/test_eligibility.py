"""Unit tests for the real §4.12.3 eligibility predicate (M9.E3).

Exercises every verdict branch through ``collector_eligibility`` (single pair)
plus the fleet-wide ``eligibility_for_candidate``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.contracts.enums import (
    CandidateState,
    GroupKind,
    IdentityRole,
    JoinedVia,
    MentionKind,
    RedundancyPolicy,
    SourceKind,
)
from eyenet.services.discovery.eligibility import (
    CollectorEligibilityResult,
    collector_eligibility,
    eligibility_for_candidate,
)
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 6, 6, tzinfo=UTC)
_ACTOR = UUID("00000000-0000-0000-0000-0000000000a1")

pytestmark = pytest.mark.unit


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _src(storage: BaseRepository) -> UUID:
    return await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )


async def _scout(storage: BaseRepository, src: UUID, name: str = "scout") -> None:
    await storage.create_identity(
        name=name, source_id=src, session_path=f"/{name}", role=IdentityRole.SCOUT
    )


async def _collector(
    storage: BaseRepository, src: UUID, name: str, *, max_depth: int | None = None
) -> UUID:
    ident = await storage.create_identity(name=f"id_{name}", source_id=src, session_path=f"/{name}")
    config = {} if max_depth is None else {"max_auto_join_depth": max_depth}
    row = await storage.create_collector(
        instance_name=f"collector-{name}",
        kind=SourceKind.TELEGRAM,
        source_id=src,
        identity_id=ident.id,
        config=config,
        created_at=_NOW,
        created_by_user_id=uuid4(),
    )
    return row.id


async def _mention(
    storage: BaseRepository,
    src: UUID,
    collector: UUID,
    *,
    seed_root: UUID | None,
    depth: int,
    groupid: str = "@target",
    evidence: str = "e1",
) -> UUID:
    cand, _ = await storage.record_candidate_mention(
        source_id=src,
        platform_groupid=groupid,
        observed_by_collector_id=collector,
        observed_in_group_id=seed_root or uuid4(),
        seed_root_id=seed_root,
        depth_from_root=depth,
        mention_evidence_ref=evidence,
        mention_kind=MentionKind.USERNAME_MENTION,
        mentioned_at_source=_NOW,
        mentioned_at_ingest=_NOW,
        mentioning_actor_id=_ACTOR,
        kind_hint=GroupKind.CHANNEL,
    )
    return cand.id


async def test_ok(storage: BaseRepository) -> None:
    src = await _src(storage)
    await _scout(storage, src)
    coll = await _collector(storage, src, "a")
    root = uuid4()
    cand = await _mention(storage, src, coll, seed_root=root, depth=1)
    verdict = await collector_eligibility(cand, coll, storage)
    assert verdict.result is CollectorEligibilityResult.OK


async def test_no_reachable_root(storage: BaseRepository) -> None:
    src = await _src(storage)
    await _scout(storage, src)
    observer = await _collector(storage, src, "obs")
    other = await _collector(storage, src, "other")
    root = uuid4()
    cand = await _mention(storage, src, observer, seed_root=root, depth=1)
    # `other` never observed the mention → can't reach the seed root
    verdict = await collector_eligibility(cand, other, storage)
    assert verdict.result is CollectorEligibilityResult.NO_REACHABLE_ROOT


async def test_over_depth(storage: BaseRepository) -> None:
    src = await _src(storage)
    await _scout(storage, src)
    coll = await _collector(storage, src, "a", max_depth=2)
    root = uuid4()
    cand = await _mention(storage, src, coll, seed_root=root, depth=3)  # 3 >= 2
    verdict = await collector_eligibility(cand, coll, storage)
    assert verdict.result is CollectorEligibilityResult.OVER_DEPTH


async def test_no_scout_available(storage: BaseRepository) -> None:
    src = await _src(storage)  # no scout created
    coll = await _collector(storage, src, "a")
    root = uuid4()
    cand = await _mention(storage, src, coll, seed_root=root, depth=1)
    verdict = await collector_eligibility(cand, coll, storage)
    assert verdict.result is CollectorEligibilityResult.NO_SCOUT_AVAILABLE


async def _joined_with_membership(
    storage: BaseRepository, src: UUID, coll: UUID, root: UUID
) -> UUID:
    """Drive a candidate to JOINED with a resulting group + one active member."""
    cand = await _mention(storage, src, coll, seed_root=root, depth=1)
    group = uuid4()
    await storage.transition_candidate(candidate_id=cand, to_state=CandidateState.QUEUED)
    await storage.transition_candidate(candidate_id=cand, to_state=CandidateState.APPROVED)
    await storage.transition_candidate(candidate_id=cand, to_state=CandidateState.JOINING)
    await storage.transition_candidate(
        candidate_id=cand, to_state=CandidateState.JOINED, resulting_group_id=group
    )
    await storage.open_membership(
        collector_id=coll, group_id=group, joined_at=_NOW, joined_via=JoinedVia.SEED
    )
    return cand


async def test_skip_dual_cover_prefer_single(storage: BaseRepository) -> None:
    src = await _src(storage)
    await _scout(storage, src)
    coll = await _collector(storage, src, "a")
    root = uuid4()
    cand = await _joined_with_membership(storage, src, coll, root)
    case = await storage.create_case(
        title="opx",
        description=None,
        opened_by_user_id=uuid4(),
        now=_NOW,
        service="t",
        instance_id="t1",
    )
    await storage.update_case_discovery_policy(
        case_id=case.id,
        seed_root_group_ids=[root],
        redundancy_policy=RedundancyPolicy.PREFER_SINGLE,
        editor_user_id=uuid4(),
        now=_NOW,
        service="t",
        instance_id="t1",
    )
    other = await _collector(storage, src, "b")
    verdict = await collector_eligibility(cand, other, storage)
    assert verdict.result is CollectorEligibilityResult.SKIP_DUAL_COVER


async def test_prefer_dual_allows_second(storage: BaseRepository) -> None:
    src = await _src(storage)
    await _scout(storage, src)
    coll = await _collector(storage, src, "a")
    root = uuid4()
    cand = await _joined_with_membership(storage, src, coll, root)
    case = await storage.create_case(
        title="opx",
        description=None,
        opened_by_user_id=uuid4(),
        now=_NOW,
        service="t",
        instance_id="t1",
    )
    await storage.update_case_discovery_policy(
        case_id=case.id,
        seed_root_group_ids=[root],
        redundancy_policy=RedundancyPolicy.PREFER_DUAL,
        editor_user_id=uuid4(),
        now=_NOW,
        service="t",
        instance_id="t1",
    )
    # second collector reaches the root (observed the same candidate's mention)
    other = await _collector(storage, src, "b")
    await _mention(storage, src, other, seed_root=root, depth=1, evidence="e2")
    verdict = await collector_eligibility(cand, other, storage)
    # one active member + prefer_dual → a second is still allowed
    assert verdict.result is CollectorEligibilityResult.OK


async def test_collector_eligibility_unknown_collector_raises(storage: BaseRepository) -> None:
    src = await _src(storage)
    coll = await _collector(storage, src, "a")
    cand = await _mention(storage, src, coll, seed_root=uuid4(), depth=1)
    with pytest.raises(ValueError, match=r"collector .* not found"):
        await collector_eligibility(cand, uuid4(), storage)


async def test_fleet_eligibility_one_per_collector(storage: BaseRepository) -> None:
    src = await _src(storage)
    await _scout(storage, src)
    a = await _collector(storage, src, "a")
    await _collector(storage, src, "b")
    root = uuid4()
    cand = await _mention(storage, src, a, seed_root=root, depth=1)
    verdicts = await eligibility_for_candidate(cand, storage)
    assert len(verdicts) == 2
    by_collector = {v.collector_id: v.result for v in verdicts}
    assert by_collector[a] is CollectorEligibilityResult.OK
    # collector b never observed → NO_REACHABLE_ROOT
    assert CollectorEligibilityResult.NO_REACHABLE_ROOT in by_collector.values()


async def test_fleet_eligibility_empty_when_no_collectors(storage: BaseRepository) -> None:
    src = await _src(storage)
    cand = await _mention(storage, src, uuid4(), seed_root=uuid4(), depth=1)
    assert await eligibility_for_candidate(cand, storage) == []
