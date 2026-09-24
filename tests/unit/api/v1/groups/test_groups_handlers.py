# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the monitored-groups handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.exceptions import RequestValidationError

from eyenet.api.deps import ConflictError, CurrentUser, ResourceNotFound
from eyenet.api.v1.groups.api_join_group import groups_join
from eyenet.api.v1.groups.api_leave_group import groups_leave
from eyenet.api.v1.groups.api_list_groups import groups_list
from eyenet.api.v1.groups.api_scan_groups import groups_scan
from eyenet.api.v1.schemas.groups import JoinGroupRequest, LeaveGroupRequest
from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts.enums import (
    CandidateState,
    CollectorObservedState,
    GroupKind,
    JoinedVia,
    SourceKind,
    SystemUserRole,
)
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _audit(storage: BaseRepository) -> AuditEmitter:
    return AuditEmitter(
        BusEnvelopePublisher(MemoryBus()), storage, service="api", instance_id="api-0"
    )


def _user() -> CurrentUser:
    return CurrentUser(
        user_id=uuid4(),
        username="op",
        role=SystemUserRole.ADMIN,
        effective_scopes=frozenset({"write:groups", "read:groups"}),
        token_expires_at=None,
    )


async def _seed_collector(storage: BaseRepository, source_id):
    now = datetime.now(tz=UTC)
    ident = await storage.create_identity(
        name=f"id{uuid4().hex[:6]}", source_id=source_id, session_path="/x"
    )
    return await storage.create_collector(
        instance_name=f"c{uuid4().hex[:6]}",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=ident.id,
        config={},
        created_at=now,
        created_by_user_id=uuid4(),
    )


async def _source(storage: BaseRepository):
    return await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=datetime.now(tz=UTC)
    )


@pytest.mark.unit
async def test_join_walks_discovered_to_approved(storage: BaseRepository) -> None:
    sid = await _source(storage)
    coll = await _seed_collector(storage, sid)
    cand = await storage.ensure_candidate(
        source_id=sid, platform_groupid="@g", seen_at=datetime.now(tz=UTC), member_dialog=True
    )
    assert cand.state is CandidateState.DISCOVERED

    result = await groups_join(
        body=JoinGroupRequest(collector_id=coll.id, candidate_id=cand.id),
        current_user=_user(),
        storage=storage,
        audit=_audit(storage),
    )
    assert result.status == "approving"
    row = await storage.get_candidate(cand.id)
    assert row is not None and row.state is CandidateState.APPROVED
    assert row.assigned_collector_id == coll.id


@pytest.mark.unit
async def test_join_unknown_collector_422(storage: BaseRepository) -> None:
    sid = await _source(storage)
    cand = await storage.ensure_candidate(
        source_id=sid, platform_groupid="@g", seen_at=datetime.now(tz=UTC)
    )
    with pytest.raises(RequestValidationError):
        await groups_join(
            body=JoinGroupRequest(collector_id=uuid4(), candidate_id=cand.id),
            current_user=_user(),
            storage=storage,
            audit=_audit(storage),
        )


@pytest.mark.unit
async def test_join_by_ref_creates_candidate(storage: BaseRepository) -> None:
    sid = await _source(storage)
    coll = await _seed_collector(storage, sid)
    result = await groups_join(
        body=JoinGroupRequest(collector_id=coll.id, source_id=sid, platform_groupid="@brand_new"),
        current_user=_user(),
        storage=storage,
        audit=_audit(storage),
    )
    assert result.platform_groupid == "@brand_new"
    assert result.status == "approving"


@pytest.mark.unit
async def test_list_groups_projects_candidates(storage: BaseRepository) -> None:
    sid = await _source(storage)
    await storage.ensure_candidate(
        source_id=sid, platform_groupid="@a", seen_at=datetime.now(tz=UTC), member_dialog=True
    )
    await storage.ensure_candidate(
        source_id=sid, platform_groupid="@b", seen_at=datetime.now(tz=UTC)
    )
    from eyenet.api.deps_paging import CursorParams

    page = await groups_list(
        _=_user(),
        storage=storage,
        page=CursorParams(offset=0, limit=50, include_total=False),
        source_id=None,
        state=None,
    )
    statuses = {i.platform_groupid: i.status for i in page.items}
    assert statuses["@a"] == "member_unmonitored"
    assert statuses["@b"] == "discovered"


@pytest.mark.unit
async def test_leave_parks_and_closes_membership(storage: BaseRepository) -> None:
    sid = await _source(storage)
    coll = await _seed_collector(storage, sid)
    cand = await storage.ensure_candidate(
        source_id=sid, platform_groupid="@g", seen_at=datetime.now(tz=UTC)
    )
    gid = await storage.upsert_group(
        source_id=sid,
        platform_groupid="@g",
        kind=GroupKind.CHANNEL,
        title="G",
        seen_at=datetime.now(tz=UTC),
    )
    # Move candidate to JOINED with resulting_group_id, and open a membership.
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.QUEUED)
    await storage.transition_candidate(
        candidate_id=cand.id, to_state=CandidateState.APPROVED, assigned_collector_id=coll.id
    )
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.JOINING)
    await storage.transition_candidate(
        candidate_id=cand.id, to_state=CandidateState.JOINED, resulting_group_id=gid
    )
    await storage.open_membership(
        collector_id=coll.id,
        group_id=gid,
        joined_at=datetime.now(tz=UTC),
        joined_via=JoinedVia.CANDIDATE,
        joined_via_candidate_id=cand.id,
    )

    result = await groups_leave(
        body=LeaveGroupRequest(candidate_id=cand.id),
        current_user=_user(),
        storage=storage,
        audit=_audit(storage),
        bus=MemoryBus(),
    )
    assert result.status == "parked"
    assert not await storage.list_active_memberships(group_id=gid)  # closed


@pytest.mark.unit
async def test_leave_non_monitored_409(storage: BaseRepository) -> None:
    sid = await _source(storage)
    cand = await storage.ensure_candidate(
        source_id=sid, platform_groupid="@g", seen_at=datetime.now(tz=UTC)
    )
    with pytest.raises(ConflictError):
        await groups_leave(
            body=LeaveGroupRequest(candidate_id=cand.id),
            current_user=_user(),
            storage=storage,
            audit=_audit(storage),
            bus=MemoryBus(),
        )


@pytest.mark.unit
async def test_scan_signals_running_collectors(storage: BaseRepository) -> None:
    sid = await _source(storage)
    coll = await _seed_collector(storage, sid)
    await storage.record_collector_observed_state(
        collector_id=coll.id, observed_state=CollectorObservedState.RUNNING
    )
    result = await groups_scan(_=_user(), storage=storage, bus=MemoryBus())
    assert result.collectors_signaled == 1


@pytest.mark.unit
async def test_join_unknown_candidate_404(storage: BaseRepository) -> None:
    sid = await _source(storage)
    coll = await _seed_collector(storage, sid)
    with pytest.raises(ResourceNotFound):
        await groups_join(
            body=JoinGroupRequest(collector_id=coll.id, candidate_id=uuid4()),
            current_user=_user(),
            storage=storage,
            audit=_audit(storage),
        )
