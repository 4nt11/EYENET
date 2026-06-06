"""Storage tests for the Group E discovery-runtime gaps (Slice 0 / D4 fold-in).

Covers the methods the §4.12.3 eligibility predicate + scout graduation need:
- IdentityMixin role/state machine + scout availability
- Case discovery-policy round-trip + `case.seed_roots_changed` audit
- candidate→Case resolution, group lineage, reachable roots
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.enums import (
    AutoJoinPolicy,
    GroupKind,
    IdentityRole,
    IdentityState,
    MentionKind,
    RedundancyPolicy,
    SourceKind,
)
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 6, 5, tzinfo=UTC)
_FAKE_COLLECTOR = UUID("00000000-0000-0000-0000-0000000000c1")
_FAKE_ACTOR = UUID("00000000-0000-0000-0000-0000000000a1")


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _source(storage: BaseRepository, name: str = "src") -> UUID:
    return await storage.upsert_source(
        kind=SourceKind.TELEGRAM,
        display_name=f"telegram:{name}",
        created_at=_NOW,
    )


async def _case(storage: BaseRepository, title: str = "operation alpha") -> UUID:
    row = await storage.create_case(
        title=title,
        description=None,
        opened_by_user_id=uuid4(),
        now=_NOW,
        service="t",
        instance_id="t1",
    )
    return row.id


# -- identities --------------------------------------------------------------


@pytest.mark.unit
async def test_create_identity_defaults_monitor_available(storage: BaseRepository) -> None:
    src = await _source(storage)
    ident = await storage.create_identity(name="i1", source_id=src, session_path="/x")
    assert ident.role is IdentityRole.MONITOR
    assert ident.state is IdentityState.AVAILABLE
    assert ident.graduated_at is None
    assert (await storage.get_identity(ident.id)).name == "i1"


@pytest.mark.unit
async def test_find_and_has_available_scout(storage: BaseRepository) -> None:
    src = await _source(storage)
    other = await _source(storage, "other")
    # a monitor + a cooling scout do NOT count
    await storage.create_identity(name="mon", source_id=src, session_path="/m")
    await storage.create_identity(
        name="cooling",
        source_id=src,
        session_path="/c",
        role=IdentityRole.SCOUT,
        state=IdentityState.COOLING,
    )
    assert await storage.has_available_scout(src) is False
    assert await storage.find_available_scout(src) is None
    # an available scout on a DIFFERENT source does not satisfy src
    await storage.create_identity(
        name="elsewhere", source_id=other, session_path="/e", role=IdentityRole.SCOUT
    )
    assert await storage.has_available_scout(src) is False
    # the real one
    scout = await storage.create_identity(
        name="scout", source_id=src, session_path="/s", role=IdentityRole.SCOUT
    )
    assert await storage.has_available_scout(src) is True
    assert (await storage.find_available_scout(src)).id == scout.id


@pytest.mark.unit
async def test_graduate_identity_promotes_and_stamps(storage: BaseRepository) -> None:
    src = await _source(storage)
    scout = await storage.create_identity(
        name="s", source_id=src, session_path="/s", role=IdentityRole.SCOUT
    )
    grad = await storage.graduate_identity(identity_id=scout.id, now=_NOW)
    assert grad.role is IdentityRole.MONITOR
    assert grad.graduated_at == _NOW
    assert await storage.has_available_scout(src) is False


@pytest.mark.unit
async def test_burn_identity_quarantines(storage: BaseRepository) -> None:
    src = await _source(storage)
    scout = await storage.create_identity(
        name="s", source_id=src, session_path="/s", role=IdentityRole.SCOUT
    )
    burned = await storage.burn_identity(identity_id=scout.id)
    assert burned.state is IdentityState.BURNED
    assert burned.role is IdentityRole.QUARANTINE


@pytest.mark.unit
async def test_set_identity_role_and_state(storage: BaseRepository) -> None:
    src = await _source(storage)
    ident = await storage.create_identity(name="i", source_id=src, session_path="/i")
    r = await storage.set_identity_role(identity_id=ident.id, role=IdentityRole.SCOUT)
    assert r.role is IdentityRole.SCOUT
    st = await storage.set_identity_state(identity_id=ident.id, state=IdentityState.FROZEN)
    assert st.state is IdentityState.FROZEN


@pytest.mark.unit
async def test_list_identities_filters(storage: BaseRepository) -> None:
    src = await _source(storage)
    await storage.create_identity(name="m1", source_id=src, session_path="/1")
    await storage.create_identity(
        name="s1", source_id=src, session_path="/2", role=IdentityRole.SCOUT
    )
    scouts = await storage.list_identities(source_id=src, role=IdentityRole.SCOUT)
    assert [i.name for i in scouts] == ["s1"]
    everyone = await storage.list_identities(source_id=src)
    assert {i.name for i in everyone} == {"m1", "s1"}


@pytest.mark.unit
async def test_set_identity_role_missing_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.set_identity_role(identity_id=uuid4(), role=IdentityRole.SCOUT)


# -- case discovery policy ---------------------------------------------------


@pytest.mark.unit
async def test_update_case_discovery_policy_roundtrip(storage: BaseRepository) -> None:
    case_id = await _case(storage)
    g1, g2 = uuid4(), uuid4()
    row = await storage.update_case_discovery_policy(
        case_id=case_id,
        seed_root_group_ids=[g1, g2],
        redundancy_policy=RedundancyPolicy.PREFER_DUAL,
        auto_join_policy=AutoJoinPolicy.SCORE_THRESHOLD,
        auto_join_score_threshold=0.75,
        editor_user_id=uuid4(),
        now=_NOW,
        service="t",
        instance_id="t1",
    )
    assert set(row.seed_root_group_ids) == {g1, g2}
    assert row.redundancy_policy is RedundancyPolicy.PREFER_DUAL
    assert row.auto_join_policy is AutoJoinPolicy.SCORE_THRESHOLD
    assert row.auto_join_score_threshold == 0.75
    # round-trips through a fresh read
    reread = await storage.get_case(case_id)
    assert set(reread.seed_root_group_ids) == {g1, g2}
    assert reread.redundancy_policy is RedundancyPolicy.PREFER_DUAL


@pytest.mark.unit
async def test_new_case_defaults_disabled_auto_join(storage: BaseRepository) -> None:
    case_id = await _case(storage)
    row = await storage.get_case(case_id)
    assert row.auto_join_policy is AutoJoinPolicy.DISABLED
    assert row.redundancy_policy is RedundancyPolicy.PREFER_SINGLE
    assert row.seed_root_group_ids == []
    assert row.auto_join_score_threshold is None


@pytest.mark.unit
async def test_seed_roots_change_emits_audit(storage: BaseRepository) -> None:
    case_id = await _case(storage)
    g1 = uuid4()
    await storage.update_case_discovery_policy(
        case_id=case_id,
        seed_root_group_ids=[g1],
        editor_user_id=uuid4(),
        now=_NOW,
        service="t",
        instance_id="t1",
    )
    events = [r.event for r in await storage.all_audit()]
    assert AuditSubject.CASE_SEED_ROOTS_CHANGED.value in events


@pytest.mark.unit
async def test_policy_only_change_does_not_emit_seed_roots_audit(
    storage: BaseRepository,
) -> None:
    case_id = await _case(storage)
    await storage.update_case_discovery_policy(
        case_id=case_id,
        redundancy_policy=RedundancyPolicy.REQUIRED_DUAL,
        editor_user_id=uuid4(),
        now=_NOW,
        service="t",
        instance_id="t1",
    )
    events = [r.event for r in await storage.all_audit()]
    assert AuditSubject.CASE_SEED_ROOTS_CHANGED.value not in events


@pytest.mark.unit
async def test_clear_score_threshold(storage: BaseRepository) -> None:
    case_id = await _case(storage)
    await storage.update_case_discovery_policy(
        case_id=case_id,
        auto_join_score_threshold=0.5,
        editor_user_id=uuid4(),
        now=_NOW,
        service="t",
        instance_id="t1",
    )
    cleared = await storage.update_case_discovery_policy(
        case_id=case_id,
        clear_score_threshold=True,
        editor_user_id=uuid4(),
        now=_NOW,
        service="t",
        instance_id="t1",
    )
    assert cleared.auto_join_score_threshold is None


# -- lineage, reachable roots, candidate→case --------------------------------


async def _mention(
    storage: BaseRepository,
    *,
    src: UUID,
    groupid: str,
    collector: UUID,
    observed_in: UUID,
    seed_root: UUID | None,
    depth: int,
    evidence: str,
) -> UUID:
    cand, _ = await storage.record_candidate_mention(
        source_id=src,
        platform_groupid=groupid,
        observed_by_collector_id=collector,
        observed_in_group_id=observed_in,
        seed_root_id=seed_root,
        depth_from_root=depth,
        mention_evidence_ref=evidence,
        mention_kind=MentionKind.USERNAME_MENTION,
        mentioned_at_source=_NOW,
        mentioned_at_ingest=_NOW,
        mentioning_actor_id=_FAKE_ACTOR,
        kind_hint=GroupKind.CHANNEL,
    )
    return cand.id


@pytest.mark.unit
async def test_group_lineage_seed_root_is_depth_zero(storage: BaseRepository) -> None:
    case_id = await _case(storage)
    root = uuid4()
    await storage.update_case_discovery_policy(
        case_id=case_id,
        seed_root_group_ids=[root],
        editor_user_id=uuid4(),
        now=_NOW,
        service="t",
        instance_id="t1",
    )
    assert await storage.group_lineage(root) == (root, 0)


@pytest.mark.unit
async def test_group_lineage_unknown_group(storage: BaseRepository) -> None:
    assert await storage.group_lineage(uuid4()) == (None, 0)


@pytest.mark.unit
async def test_group_lineage_discovered_group(storage: BaseRepository) -> None:
    src = await _source(storage)
    root = uuid4()
    cand_id = await _mention(
        storage,
        src=src,
        groupid="@child",
        collector=_FAKE_COLLECTOR,
        observed_in=root,
        seed_root=root,
        depth=1,
        evidence="tg:1:1",
    )
    # promote the candidate to a resulting group
    joined_group = uuid4()
    # walk the legal state machine: discovered→queued→approved→joining→joined
    from eyenet.contracts.enums import CandidateState

    await storage.transition_candidate(candidate_id=cand_id, to_state=CandidateState.QUEUED)
    await storage.transition_candidate(candidate_id=cand_id, to_state=CandidateState.APPROVED)
    await storage.transition_candidate(candidate_id=cand_id, to_state=CandidateState.JOINING)
    await storage.transition_candidate(
        candidate_id=cand_id, to_state=CandidateState.JOINED, resulting_group_id=joined_group
    )
    assert await storage.group_lineage(joined_group) == (root, 1)


@pytest.mark.unit
async def test_resolve_case_for_candidate(storage: BaseRepository) -> None:
    src = await _source(storage)
    case_id = await _case(storage)
    root = uuid4()
    await storage.update_case_discovery_policy(
        case_id=case_id,
        seed_root_group_ids=[root],
        editor_user_id=uuid4(),
        now=_NOW,
        service="t",
        instance_id="t1",
    )
    cand_id = await _mention(
        storage,
        src=src,
        groupid="@t",
        collector=_FAKE_COLLECTOR,
        observed_in=root,
        seed_root=root,
        depth=1,
        evidence="tg:9:9",
    )
    resolved = await storage.resolve_case_for_candidate(cand_id)
    assert resolved is not None
    assert resolved.id == case_id


@pytest.mark.unit
async def test_resolve_case_for_candidate_no_match(storage: BaseRepository) -> None:
    src = await _source(storage)
    await _case(storage)  # a case with no seed roots
    cand_id = await _mention(
        storage,
        src=src,
        groupid="@t",
        collector=_FAKE_COLLECTOR,
        observed_in=uuid4(),
        seed_root=uuid4(),
        depth=1,
        evidence="tg:5:5",
    )
    assert await storage.resolve_case_for_candidate(cand_id) is None


@pytest.mark.unit
async def test_reachable_roots_for_collector(storage: BaseRepository) -> None:
    src = await _source(storage)
    root = uuid4()
    await _mention(
        storage,
        src=src,
        groupid="@t",
        collector=_FAKE_COLLECTOR,
        observed_in=root,
        seed_root=root,
        depth=1,
        evidence="tg:7:7",
    )
    reachable = await storage.reachable_roots_for_collector(_FAKE_COLLECTOR)
    assert root in reachable
    # a different collector sees nothing
    assert await storage.reachable_roots_for_collector(uuid4()) == set()
