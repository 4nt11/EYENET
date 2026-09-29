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


async def _seed_forum_collector(storage: BaseRepository, source_id):
    now = datetime.now(tz=UTC)
    ident = await storage.create_identity(
        name=f"fid{uuid4().hex[:6]}", source_id=source_id, session_path="/x"
    )
    return await storage.create_collector(
        instance_name=f"cf{uuid4().hex[:6]}",
        kind=SourceKind.FORUM,
        source_id=source_id,
        identity_id=ident.id,
        config={},
        created_at=now,
        created_by_user_id=uuid4(),
    )


@pytest.mark.unit
async def test_monitor_forum_category_opens_internal_membership(storage: BaseRepository) -> None:
    now = datetime.now(tz=UTC)
    sid = await storage.upsert_source(kind=SourceKind.FORUM, display_name="f", created_at=now)
    coll = await _seed_forum_collector(storage, sid)
    cand = await storage.ensure_candidate(
        source_id=sid,
        platform_groupid="Forum-Databases",
        seen_at=now,
        kind=GroupKind.FORUM_CATEGORY,
    )

    result = await groups_join(
        body=JoinGroupRequest(collector_id=coll.id, candidate_id=cand.id),
        current_user=_user(),
        storage=storage,
        audit=_audit(storage),
    )
    assert result.status == "monitored"  # completed synchronously, not "approving"

    row = await storage.get_candidate(cand.id)
    assert row is not None and row.state is CandidateState.JOINED
    assert row.resulting_group_id is not None
    memberships = await storage.list_active_memberships(collector_id=coll.id)
    assert len(memberships) == 1
    assert memberships[0].joined_via is JoinedVia.CANDIDATE

    # Idempotent: monitoring an already-JOINED category does not double-open.
    await groups_join(
        body=JoinGroupRequest(collector_id=coll.id, candidate_id=cand.id),
        current_user=_user(),
        storage=storage,
        audit=_audit(storage),
    )
    assert len(await storage.list_active_memberships(collector_id=coll.id)) == 1


@pytest.mark.unit
async def test_groups_messages_returns_thread_posts_oldest_first(storage: BaseRepository) -> None:
    from datetime import timedelta

    from eyenet.api.deps_paging import CursorParams
    from eyenet.api.v1.groups.api_list_group_messages import groups_messages
    from eyenet.models import MessageTable
    from eyenet.models._base import new_uuid7

    now = datetime.now(tz=UTC)
    sid = await storage.upsert_source(kind=SourceKind.FORUM, display_name="f", created_at=now)
    gid = await storage.upsert_group(
        source_id=sid, platform_groupid="42", kind=GroupKind.FORUM_THREAD, title="t", seen_at=now
    )
    aid = await storage.upsert_actor(
        source_id=sid,
        actor_key="actor:x",
        platform_userid="p",
        handle="h",
        display_name="d",
        seen_at=now,
    )
    for i, body in enumerate(["first", "second"]):
        await storage.put_message(
            MessageTable(
                id=new_uuid7(),
                source_id=sid,
                group_id=gid,
                actor_id=aid,
                platform_msgid=str(i),
                evidence_ref=f"forum:b:42:{i}",
                body=body,
                length_chars=len(body),
                length_words=1,
                sent_at_source=now + timedelta(seconds=i),
                ingested_at=now,
                has_attachment=False,
                source_specific={"body_html": f"<p>{body}</p>", "author_display": "d"},
            ),
            [],
        )

    page = await groups_messages(
        group_id=gid,
        _=_user(),
        storage=storage,
        page=CursorParams(offset=0, limit=50, include_total=True),
    )
    assert [m.body for m in page.items] == ["first", "second"]  # oldest-first
    assert page.items[0].body_html == "<p>first</p>"
    assert page.items[0].author_display == "d"
    assert page.estimated_total == 2


@pytest.mark.unit
async def test_groups_messages_unknown_group_404(storage: BaseRepository) -> None:
    from uuid import uuid4

    from eyenet.api.deps_paging import CursorParams
    from eyenet.api.v1.groups.api_list_group_messages import groups_messages

    with pytest.raises(ResourceNotFound):
        await groups_messages(
            group_id=uuid4(),
            _=_user(),
            storage=storage,
            page=CursorParams(offset=0, limit=50, include_total=False),
        )
