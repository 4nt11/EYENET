# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call test for GET /v1/actor-groups (crews over shared_infra links)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser
from eyenet.api.v1.actor_groups.api_list_actor_groups import actor_groups_list
from eyenet.contracts.enums import SourceKind, SystemUserRole
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _user() -> CurrentUser:
    return CurrentUser(
        user_id=uuid4(),
        username="op",
        role=SystemUserRole.ADMIN,
        effective_scopes=frozenset({"read:actors"}),
        token_expires_at=None,
    )


async def _actor(storage: BaseRepository, src, uid: str, *, handle=None, display=None):
    return await storage.upsert_actor(
        source_id=src,
        actor_key=f"actor:tg:{uid}",
        platform_userid=uid,
        handle=handle,
        display_name=display,
        seen_at=datetime.now(tz=UTC),
    )


@pytest.mark.unit
async def test_actor_groups_clusters_and_labels(storage: BaseRepository) -> None:
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=datetime.now(tz=UTC)
    )
    a = await _actor(storage, src, "101", display="Nicole Lee")
    b = await _actor(storage, src, "102", handle="@boss")
    c = await _actor(storage, src, "201")  # no handle, no display -> id fallback
    d = await _actor(storage, src, "202", display="SoSo dropshipping")

    # Crew 1: a-b share @wbpay. Crew 2: c-d share @lv.
    await storage.insert_proposed_linkage(
        actor_a=a,
        actor_b=b,
        method="shared_infra",
        score=0.9,
        evidence={"shared": ["handle:wbpay_mm1888"]},
    )
    await storage.insert_proposed_linkage(
        actor_a=c,
        actor_b=d,
        method="shared_infra",
        score=0.7,
        evidence={"shared": ["handle:lv000098"]},
    )
    # A stylometric edge must NOT create a crew.
    await storage.insert_proposed_linkage(
        actor_a=a,
        actor_b=c,
        method="char_ngram_simhash_hamming",
        score=1.0,
        evidence={},
    )

    result = await actor_groups_list(_user(), storage)
    assert result.count == 2
    sizes = {g.size for g in result.items}
    assert sizes == {2}
    # Labels resolve: handle > display > id.
    all_labels = {m.label for g in result.items for m in g.members}
    assert "@boss" in all_labels
    assert "Nicole Lee" in all_labels
    assert "SoSo dropshipping" in all_labels
    assert "201" in all_labels  # id fallback
    # Shared infra surfaced.
    infra = {i for g in result.items for i in g.top_infra}
    assert "handle:wbpay_mm1888" in infra and "handle:lv000098" in infra


@pytest.mark.unit
async def test_actor_groups_empty(storage: BaseRepository) -> None:
    result = await actor_groups_list(_user(), storage)
    assert result.count == 0
    assert result.items == []


@pytest.mark.unit
async def test_open_crew_case_promotes_and_is_idempotent(storage: BaseRepository) -> None:
    from eyenet.api.v1.actor_groups.api_open_crew_case import actor_groups_open_case
    from eyenet.api.v1.schemas.actor_groups import OpenCrewCaseRequest
    from eyenet.bus.memory import MemoryBus
    from eyenet.bus.publisher import BusEnvelopePublisher
    from eyenet.telemetry.audit import AuditEmitter

    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=datetime.now(tz=UTC)
    )
    a = await _actor(storage, src, "1", display="A")
    b = await _actor(storage, src, "2", display="B")
    audit = AuditEmitter(
        BusEnvelopePublisher(MemoryBus()), storage, service="api", instance_id="api-0"
    )

    def _writer() -> CurrentUser:
        return CurrentUser(
            user_id=uuid4(),
            username="op",
            role=SystemUserRole.ADMIN,
            effective_scopes=frozenset({"write:cases"}),
            token_expires_at=None,
        )

    body = OpenCrewCaseRequest(members=[a, b], top_infra=["handle:wbpay_mm1888"])
    r1 = await actor_groups_open_case(body, _writer(), storage, audit)
    r2 = await actor_groups_open_case(body, _writer(), storage, audit)
    assert r1.case_id == r2.case_id  # idempotent on crew_key
    assert r1.crew_key == "handle:wbpay_mm1888"
    case = await storage.get_case_by_crew_key("handle:wbpay_mm1888")
    assert case is not None and case.id == r1.case_id
