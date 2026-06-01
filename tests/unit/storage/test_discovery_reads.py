# SPDX-License-Identifier: AGPL-3.0-or-later
"""Storage tests for the M9.D1-D3 read/aggregate surface (Group D slice 0).

Covers the methods Group C did NOT ship but the Discovery API needs:
list/count sources, list source domains, swap primary, bridge-summary;
paginated list_collectors, count, update, fleet-health; filtered
list_candidates + count.

Default fixture: BaseRepository via the factory (CLAUDE.md §2.3 Rule 2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.contracts.collector import CollectorFleetHealth
from eyenet.contracts.enums import (
    CandidateState,
    CollectorObservedState,
    GroupKind,
    IdentityState,
    InfrastructureKind,
    MentionKind,
    ResolutionState,
    SourceDomainPatternKind,
    SourceKind,
)
from eyenet.contracts.source import SourceBridgeSummary
from eyenet.models.candidates import GroupCandidateTable
from eyenet.models.identity import IdentityTable
from eyenet.models.infrastructure import InfrastructureArtifactTable
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 5, 25, tzinfo=UTC)
_OPERATOR = UUID("00000000-0000-0000-0000-000000000001")
_FAKE_COLLECTOR = UUID("00000000-0000-0000-0000-0000000000c0")
_FAKE_ACTOR = UUID("00000000-0000-0000-0000-0000000000a0")


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _make_source(storage: BaseRepository, name: str, *, at: datetime = _NOW) -> UUID:
    return await storage.upsert_source(
        kind=SourceKind.TELEGRAM,
        display_name=f"telegram:{name}",
        created_at=at,
    )


async def _make_identity(storage: BaseRepository, source_id: UUID, name: str) -> UUID:
    async with storage.session() as session:
        row = IdentityTable(
            name=name,
            source_id=source_id,
            session_path=f"/tmp/{name}.session",  # noqa: S108 — test stub, never opened
            state=IdentityState.AVAILABLE,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


async def _make_collector(
    storage: BaseRepository,
    source_id: UUID,
    name: str,
    *,
    at: datetime = _NOW,
) -> UUID:
    identity_id = await _make_identity(storage, source_id, f"id_{name}")
    row = await storage.create_collector(
        instance_name=f"collector_{name}",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=identity_id,
        config={"kind": "telegram", "telegram_api_hash": "deadbeef"},
        created_at=at,
        created_by_user_id=_OPERATOR,
    )
    return row.id


# =====================================================================
# Sources — list / count
# =====================================================================


@pytest.mark.unit
async def test_list_sources_paginates_created_at_asc(storage: BaseRepository) -> None:
    await _make_source(storage, "a", at=datetime(2025, 1, 1, tzinfo=UTC))
    await _make_source(storage, "b", at=datetime(2025, 6, 1, tzinfo=UTC))
    await _make_source(storage, "c", at=datetime(2026, 1, 1, tzinfo=UTC))

    page1 = await storage.list_sources(limit=2, offset=0)
    assert [s.display_name for s in page1] == ["telegram:a", "telegram:b"]
    page2 = await storage.list_sources(limit=2, offset=2)
    assert [s.display_name for s in page2] == ["telegram:c"]
    assert await storage.count_sources() == 3


@pytest.mark.unit
async def test_count_sources_empty(storage: BaseRepository) -> None:
    assert await storage.count_sources() == 0


# =====================================================================
# SourceDomains — list / swap primary
# =====================================================================


@pytest.mark.unit
async def test_list_source_domains_excludes_removed_by_default(
    storage: BaseRepository,
) -> None:
    src = await _make_source(storage, "dom")
    d1 = await storage.add_source_domain(
        source_id=src,
        pattern="alpha.example",
        pattern_kind=SourceDomainPatternKind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    await storage.add_source_domain(
        source_id=src,
        pattern="beta.example",
        pattern_kind=SourceDomainPatternKind.EXACT,
        is_primary=False,
        created_at=_NOW,
    )
    await storage.remove_source_domain(
        domain_id=d1.id, removed_at=_NOW, removed_by_user_id=_OPERATOR
    )

    active = await storage.list_source_domains(source_id=src)
    assert {d.pattern for d in active} == {"beta.example"}
    allrows = await storage.list_source_domains(source_id=src, include_removed=True)
    assert {d.pattern for d in allrows} == {"alpha.example", "beta.example"}


@pytest.mark.unit
async def test_swap_source_domain_primary(storage: BaseRepository) -> None:
    src = await _make_source(storage, "swap")
    d1 = await storage.add_source_domain(
        source_id=src,
        pattern="one.example",
        pattern_kind=SourceDomainPatternKind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    d2 = await storage.add_source_domain(
        source_id=src,
        pattern="two.example",
        pattern_kind=SourceDomainPatternKind.EXACT,
        is_primary=False,
        created_at=_NOW,
    )
    swapped = await storage.swap_source_domain_primary(source_id=src, domain_id=d2.id)
    assert swapped.is_primary is True
    domains = {d.id: d for d in await storage.list_source_domains(source_id=src)}
    assert domains[d1.id].is_primary is False
    assert domains[d2.id].is_primary is True


@pytest.mark.unit
async def test_swap_primary_rejects_foreign_domain(storage: BaseRepository) -> None:
    src = await _make_source(storage, "owner")
    other = await _make_source(storage, "other")
    foreign = await storage.add_source_domain(
        source_id=other,
        pattern="foreign.example",
        pattern_kind=SourceDomainPatternKind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    with pytest.raises(ValueError, match="not found for source"):
        await storage.swap_source_domain_primary(source_id=src, domain_id=foreign.id)


@pytest.mark.unit
async def test_swap_primary_rejects_removed_domain(storage: BaseRepository) -> None:
    src = await _make_source(storage, "rm")
    d1 = await storage.add_source_domain(
        source_id=src,
        pattern="gone.example",
        pattern_kind=SourceDomainPatternKind.EXACT,
        is_primary=False,
        created_at=_NOW,
    )
    await storage.remove_source_domain(
        domain_id=d1.id, removed_at=_NOW, removed_by_user_id=_OPERATOR
    )
    with pytest.raises(ValueError, match="removed"):
        await storage.swap_source_domain_primary(source_id=src, domain_id=d1.id)


# =====================================================================
# Source bridge-summary
# =====================================================================


@pytest.mark.unit
async def test_bridge_summary_empty(storage: BaseRepository) -> None:
    src = await _make_source(storage, "bs")
    summary = await storage.source_bridge_summary(source_id=src)
    assert isinstance(summary, SourceBridgeSummary)
    assert summary.source_id == src
    assert (summary.resolved, summary.unresolved, summary.ambiguous, summary.not_applicable) == (
        0,
        0,
        0,
        0,
    )


@pytest.mark.unit
async def test_bridge_summary_counts_by_state(storage: BaseRepository) -> None:
    src = await _make_source(storage, "bs2")
    kind = next(iter(InfrastructureKind))
    async with storage.session() as session:
        session.add(
            InfrastructureArtifactTable(
                kind=kind,
                value="r.example",
                value_hash="h-resolved",
                first_seen_at_ingest=_NOW,
                last_seen_at_ingest=_NOW,
                resolved_to_source_id=src,
                resolution_state=ResolutionState.RESOLVED,
            )
        )
        for state, vh in (
            (ResolutionState.UNRESOLVED, "h-unres"),
            (ResolutionState.AMBIGUOUS, "h-amb"),
            (ResolutionState.NOT_APPLICABLE, "h-na"),
        ):
            session.add(
                InfrastructureArtifactTable(
                    kind=kind,
                    value=f"{vh}.example",
                    value_hash=vh,
                    first_seen_at_ingest=_NOW,
                    last_seen_at_ingest=_NOW,
                    resolved_to_source_id=None,
                    resolution_state=state,
                )
            )
        await session.commit()

    summary = await storage.source_bridge_summary(source_id=src)
    assert summary.resolved == 1
    assert summary.unresolved == 1
    assert summary.ambiguous == 1
    assert summary.not_applicable == 1


# =====================================================================
# Collectors — pagination / count / update / fleet-health
# =====================================================================


@pytest.mark.unit
async def test_list_collectors_pagination_and_count(storage: BaseRepository) -> None:
    src = await _make_source(storage, "col")
    await _make_collector(storage, src, "a", at=datetime(2025, 1, 1, tzinfo=UTC))
    await _make_collector(storage, src, "b", at=datetime(2025, 6, 1, tzinfo=UTC))
    await _make_collector(storage, src, "c", at=datetime(2026, 1, 1, tzinfo=UTC))

    # No limit → all (supervisor view, back-compat).
    assert len(await storage.list_collectors()) == 3
    page = await storage.list_collectors(limit=2, offset=1)
    assert [c.instance_name for c in page] == ["collector_b", "collector_c"]
    assert await storage.count_collectors() == 3


@pytest.mark.unit
async def test_update_collector_partial(storage: BaseRepository) -> None:
    src = await _make_source(storage, "upd")
    cid = await _make_collector(storage, src, "x")
    updated = await storage.update_collector(
        collector_id=cid,
        instance_name="renamed",
        notes="commissioned",
    )
    assert updated.instance_name == "renamed"
    assert updated.notes == "commissioned"
    # config left unchanged (None = leave as-is)
    assert updated.config["telegram_api_hash"] == "deadbeef"

    # Now update config only; name/notes preserved.
    again = await storage.update_collector(
        collector_id=cid,
        config={"kind": "telegram", "telegram_api_hash": "rotated"},
    )
    assert again.instance_name == "renamed"
    assert again.notes == "commissioned"
    assert again.config["telegram_api_hash"] == "rotated"


@pytest.mark.unit
async def test_update_collector_unknown_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.update_collector(collector_id=uuid4(), notes="x")


@pytest.mark.unit
async def test_collector_fleet_health(storage: BaseRepository) -> None:
    src = await _make_source(storage, "fleet")
    running = await _make_collector(storage, src, "run")
    crashed = await _make_collector(storage, src, "crash")
    await _make_collector(storage, src, "idle")  # stays STOPPED

    hb = datetime(2026, 5, 25, 9, 0, tzinfo=UTC)
    await storage.record_collector_observed_state(
        collector_id=running,
        observed_state=CollectorObservedState.RUNNING,
        last_heartbeat_at=hb,
    )
    await storage.record_collector_observed_state(
        collector_id=crashed,
        observed_state=CollectorObservedState.CRASHED,
        last_error_type="FloodWaitError",
        last_error_message="banned",
        restart_count=4,
        last_heartbeat_at=datetime(2026, 5, 25, 10, 0, tzinfo=UTC),
    )

    health = await storage.collector_fleet_health()
    assert isinstance(health, CollectorFleetHealth)
    assert health.total == 3
    assert health.counts_by_observed_state[CollectorObservedState.STOPPED] == 1
    assert health.counts_by_observed_state[CollectorObservedState.RUNNING] == 1
    assert health.counts_by_observed_state[CollectorObservedState.CRASHED] == 1
    # Oldest live heartbeat among non-STOPPED is the RUNNING one (09:00 < 10:00).
    assert health.oldest_heartbeat_at == hb
    assert health.restart_storm_leader_id == crashed
    assert health.max_restart_count == 4


@pytest.mark.unit
async def test_fleet_health_empty(storage: BaseRepository) -> None:
    health = await storage.collector_fleet_health()
    assert health.total == 0
    assert health.oldest_heartbeat_at is None
    assert health.restart_storm_leader_id is None
    assert health.max_restart_count == 0


# =====================================================================
# Candidates — filtered list / count
# =====================================================================


async def _record_candidate(
    storage: BaseRepository,
    source_id: UUID,
    group_id: UUID,
    *,
    platform_groupid: str,
    evidence_ref: str,
) -> UUID:
    candidate, _ = await storage.record_candidate_mention(
        source_id=source_id,
        platform_groupid=platform_groupid,
        observed_by_collector_id=_FAKE_COLLECTOR,
        observed_in_group_id=group_id,
        seed_root_id=None,
        depth_from_root=1,
        mention_evidence_ref=evidence_ref,
        mention_kind=MentionKind.USERNAME_MENTION,
        mentioned_at_source=_NOW,
        mentioned_at_ingest=_NOW,
        mentioning_actor_id=_FAKE_ACTOR,
    )
    return candidate.id


@pytest.mark.unit
async def test_list_candidates_filters_by_state_and_source(
    storage: BaseRepository,
) -> None:
    src = await _make_source(storage, "cand")
    grp = await storage.upsert_group(
        source_id=src,
        platform_groupid="root",
        kind=GroupKind.CHANNEL,
        title="root",
        seen_at=_NOW,
    )
    other = await _make_source(storage, "cand_other")

    c1 = await _record_candidate(storage, src, grp, platform_groupid="g1", evidence_ref="ref:1")
    await _record_candidate(storage, src, grp, platform_groupid="g2", evidence_ref="ref:2")

    # all under src
    assert await storage.count_candidates() == 2
    rows = await storage.list_candidates(limit=10)
    assert len(rows) == 2

    # filter by state — none QUEUED yet
    assert await storage.count_candidates(state=CandidateState.QUEUED) == 0
    await storage.transition_candidate(candidate_id=c1, to_state=CandidateState.QUEUED)
    queued = await storage.list_candidates(state=CandidateState.QUEUED, limit=10)
    assert [r.id for r in queued] == [c1]

    # filter by source
    assert await storage.count_candidates(source_id=other) == 0
    assert await storage.count_candidates(source_id=src) == 2


@pytest.mark.unit
async def test_list_candidates_min_score_and_sort(storage: BaseRepository) -> None:
    src = await _make_source(storage, "score")
    # Insert candidates with explicit scores via the escape hatch (no public
    # score setter — scoring is the sensor's job, not this slice's).
    async with storage.session() as session:
        for pg, score, last in (
            ("low", 0.5, datetime(2026, 5, 20, tzinfo=UTC)),
            ("high", 9.0, datetime(2026, 5, 21, tzinfo=UTC)),
            ("mid", 5.0, datetime(2026, 5, 22, tzinfo=UTC)),
        ):
            session.add(
                GroupCandidateTable(
                    source_id=src,
                    platform_groupid=pg,
                    state=CandidateState.DISCOVERED,
                    score=score,
                    score_breakdown={},
                    score_function_version=1,
                    first_observed_at_ingest=last,
                    last_observed_at_ingest=last,
                )
            )
        await session.commit()

    # min_score filters out the 0.5 row.
    assert await storage.count_candidates(min_score=1.0) == 2
    ordered = await storage.list_candidates(min_score=1.0, limit=10)
    # score DESC → high (9.0) then mid (5.0)
    assert [r.platform_groupid for r in ordered] == ["high", "mid"]
