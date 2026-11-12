# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the D2 Collectors handlers (M9.D2).

Bypasses ASGI routing (coverage can't trace it); scope/redaction *enforcement*
via RequireScope is ASGI-level (slice-4 smoke). Config redaction logic IS
exercised here by passing CurrentUsers with/without read:collectors_config.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.exceptions import RequestValidationError

from eyenet.api.deps import ConflictError, CurrentUser, ResourceNotFound
from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.collectors.api_collector_health import collectors_health
from eyenet.api.v1.collectors.api_create_collector import collectors_create
from eyenet.api.v1.collectors.api_delete_collector import collectors_delete
from eyenet.api.v1.collectors.api_get_collector import collectors_get
from eyenet.api.v1.collectors.api_list_collectors import collectors_list
from eyenet.api.v1.collectors.api_list_memberships import collectors_list_memberships
from eyenet.api.v1.collectors.api_start_collector import collectors_start
from eyenet.api.v1.collectors.api_stop_collector import collectors_stop
from eyenet.api.v1.collectors.api_update_collector import collectors_update
from eyenet.api.v1.schemas.collectors import CreateCollectorRequest, UpdateCollectorRequest
from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts.enums import (
    CollectorDesiredState,
    CollectorObservedState,
    IdentityState,
    JoinedVia,
    SourceKind,
)
from eyenet.models.identity import IdentityTable
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

pytestmark = pytest.mark.unit

_SECRET_CONFIG = {"kind": "telegram", "telegram_api_hash": "topsecret"}


@pytest.fixture
def audit(storage: BaseRepository) -> AuditEmitter:
    return AuditEmitter(
        BusEnvelopePublisher(MemoryBus()), storage, service="test", instance_id="t0"
    )


async def _source(storage: BaseRepository) -> UUID:
    return await storage.upsert_source(
        kind=SourceKind.TELEGRAM,
        display_name="telegram:fleet",
        created_at=datetime(2026, 5, 26, tzinfo=UTC),
    )


async def _identity(storage: BaseRepository, source_id: UUID, name: str) -> UUID:
    async with storage.session() as session:
        row = IdentityTable(
            name=name,
            source_id=source_id,
            session_path=f"/tmp/{name}.session",  # noqa: S108 — test stub
            state=IdentityState.AVAILABLE,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


async def _make(
    storage: BaseRepository,
    audit: AuditEmitter,
    user: CurrentUser,
    name: str = "tg01",
) -> UUID:
    src = await _source(storage)
    ident = await _identity(storage, src, name)
    detail = await collectors_create(
        CreateCollectorRequest(
            instance_name=f"collector_{name}",
            kind=SourceKind.TELEGRAM,
            source_id=src,
            identity_id=ident,
            config=dict(_SECRET_CONFIG),
        ),
        user,
        storage,
        audit,
    )
    return detail.collector_id


def _page(limit: int = 50, *, include_total: bool = False) -> CursorParams:
    return CursorParams(offset=0, limit=limit, include_total=include_total)


# --- create + redaction + get ---------------------------------------------


async def test_create_redacts_config_without_grant(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser("write:collectors")  # no read:collectors_config
    cid = await _make(storage, audit, user)
    detail = await collectors_get(cid, mkuser("read:collectors"), storage)
    assert detail.config == {"__redacted__": True, "kind": "telegram"}
    assert "telegram_api_hash" not in detail.config


async def test_get_exposes_config_with_grant(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    cid = await _make(storage, audit, mkuser("write:collectors"))
    privileged = mkuser("read:collectors", "read:collectors_config")
    detail = await collectors_get(cid, privileged, storage)
    assert detail.config["telegram_api_hash"] == "topsecret"


async def test_get_unknown_404(storage: BaseRepository, mkuser: Callable[..., CurrentUser]) -> None:
    with pytest.raises(ResourceNotFound):
        await collectors_get(uuid4(), mkuser("read:collectors"), storage)


async def test_create_rejects_cross_source_identity(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    # A collector may only run an identity of its OWN source; pairing one from a
    # different source desyncs candidate attribution and must be refused (422).
    src_a = await _source(storage)
    src_b = await storage.upsert_source(
        kind=SourceKind.TELEGRAM,
        display_name="telegram:other",
        created_at=datetime(2026, 5, 27, tzinfo=UTC),
    )
    ident_b = await _identity(storage, src_b, "cross")
    with pytest.raises(RequestValidationError, match="must match"):
        await collectors_create(
            CreateCollectorRequest(
                instance_name="collector_cross",
                kind=SourceKind.TELEGRAM,
                source_id=src_a,
                identity_id=ident_b,
                config=dict(_SECRET_CONFIG),
            ),
            mkuser("write:collectors"),
            storage,
            audit,
        )


async def test_list_collectors_paginates(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser("write:collectors")
    src = await _source(storage)
    for i in range(3):
        ident = await _identity(storage, src, f"id{i}")
        await collectors_create(
            CreateCollectorRequest(
                instance_name=f"collector{i}",
                kind=SourceKind.TELEGRAM,
                source_id=src,
                identity_id=ident,
                config={"kind": "telegram"},
            ),
            user,
            storage,
            audit,
        )
    page = await collectors_list(
        mkuser("read:collectors"), storage, _page(limit=2, include_total=True)
    )
    assert len(page.items) == 2
    assert page.estimated_total == 3


# --- update / start / stop -------------------------------------------------


async def test_update_collector(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser("write:collectors")
    cid = await _make(storage, audit, user)
    updated = await collectors_update(
        cid,
        UpdateCollectorRequest(notes="rotated", desired_state=CollectorDesiredState.RUNNING),
        user,
        storage,
        audit,
    )
    assert updated.notes == "rotated"
    assert updated.desired_state is CollectorDesiredState.RUNNING


async def test_backfill_on_join_toggle_persists(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    # The opt-out must be reachable over the API as a first-class field, and the
    # read model must reflect the effective state (default ON when absent).
    user = mkuser("write:collectors", "read:collectors_config")
    cid = await _make(storage, audit, user)
    fresh = await collectors_update(cid, UpdateCollectorRequest(notes="x"), user, storage, audit)
    assert fresh.backfill_on_join is True  # default ON, no config key set

    # Opt out via the single boolean; it folds into config AND composes with a
    # one-shot backfill request in the same PATCH.
    updated = await collectors_update(
        cid,
        UpdateCollectorRequest(backfill_on_join=False, backfill=True),
        user,
        storage,
        audit,
    )
    assert updated.backfill_on_join is False
    assert updated.config["backfill_on_join"] is False
    assert updated.config["_backfill_pending"] is True


async def test_start_and_stop(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser("write:collectors")
    cid = await _make(storage, audit, user)
    started = await collectors_start(cid, user, storage, audit)
    assert started.desired_state is CollectorDesiredState.RUNNING
    # observed_state untouched (supervisor owns it) — still STOPPED.
    assert started.observed_state is CollectorObservedState.STOPPED
    stopped = await collectors_stop(cid, user, storage, audit)
    assert stopped.desired_state is CollectorDesiredState.STOPPED


async def test_start_unknown_404(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    with pytest.raises(ResourceNotFound):
        await collectors_start(uuid4(), mkuser("write:collectors"), storage, audit)


# --- delete ----------------------------------------------------------------


async def test_delete_stopped_collector(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    admin = mkuser("write:collectors", "admin:collectors")
    cid = await _make(storage, audit, admin)
    await collectors_delete(cid, admin, storage, audit)
    assert await storage.get_collector(cid) is None


async def test_delete_running_collector_conflict(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    admin = mkuser("write:collectors", "admin:collectors")
    cid = await _make(storage, audit, admin)
    await storage.record_collector_observed_state(
        collector_id=cid,
        observed_state=CollectorObservedState.RUNNING,
        last_heartbeat_at=datetime(2026, 5, 26, tzinfo=UTC),
    )
    with pytest.raises(ConflictError, match="stop it before deletion"):
        await collectors_delete(cid, admin, storage, audit)


# --- memberships + health --------------------------------------------------


async def test_list_memberships(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    admin = mkuser("write:collectors")
    cid = await _make(storage, audit, admin)
    assert await collectors_list_memberships(cid, mkuser("read:collectors"), storage) == []
    group_id = uuid4()
    await storage.open_membership(
        collector_id=cid,
        group_id=group_id,
        joined_at=datetime(2026, 5, 26, tzinfo=UTC),
        joined_via=JoinedVia.MANUAL,
    )
    rows = await collectors_list_memberships(cid, mkuser("read:collectors"), storage)
    assert [r.group_id for r in rows] == [group_id]


async def test_fleet_health(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    await _make(storage, audit, mkuser("write:collectors"))
    health = await collectors_health(mkuser("read:collectors"), storage)
    assert health.total == 1
    assert health.counts_by_observed_state[CollectorObservedState.STOPPED] == 1


# --- rediscover -------------------------------------------------------------


async def test_rediscover_unknown_404(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    from eyenet.api.v1.collectors.api_rediscover_collector import collectors_rediscover

    with pytest.raises(ResourceNotFound):
        await collectors_rediscover(uuid4(), mkuser("write:groups"), storage, MemoryBus(), audit)


async def test_rediscover_stopped_signals_zero(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    from eyenet.api.v1.collectors.api_rediscover_collector import collectors_rediscover

    cid = await _make(storage, audit, mkuser("write:collectors"))  # observed STOPPED by default
    res = await collectors_rediscover(cid, mkuser("write:groups"), storage, MemoryBus(), audit)
    assert res.collectors_signaled == 0


async def test_rediscover_running_signals_one(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    from eyenet.api.v1.collectors.api_rediscover_collector import collectors_rediscover

    cid = await _make(storage, audit, mkuser("write:collectors"))
    await storage.record_collector_observed_state(
        collector_id=cid,
        observed_state=CollectorObservedState.RUNNING,
        last_heartbeat_at=datetime.now(tz=UTC),
    )
    res = await collectors_rediscover(cid, mkuser("write:groups"), storage, MemoryBus(), audit)
    assert res.collectors_signaled == 1
