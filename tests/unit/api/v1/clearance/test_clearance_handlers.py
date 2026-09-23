# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the §4.8 clearance grant handlers.

ASGI-routed handlers do not trace for coverage (see memory project_m9_f_done),
so handlers are called directly with an in-memory ``BaseRepository``. Storage
self-audits grant/revoke; the handler only needs ``audit.service`` /
``audit.instance_id`` so a lightweight namespace stands in for the emitter.

The handlers evaluate ACTIVE(now) and revoke against real wall-clock time, so
future-valid grants are seeded relative to ``datetime.now(UTC)`` (not the past
``now`` fixture, which is reserved for the already-expired path).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser, ResourceNotFound, UnprocessableError
from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.clearance.api_get_grant import clearance_get_grant
from eyenet.api.v1.clearance.api_grant_clearance import clearance_grant
from eyenet.api.v1.clearance.api_list_grants import clearance_list_grants
from eyenet.api.v1.clearance.api_revoke_grant import clearance_revoke_grant
from eyenet.api.v1.schemas.clearance import ClearanceGrantRequest, ClearanceRevokeRequest
from eyenet.contracts.enums import ClearanceScope, SystemUserRole
from eyenet.storage.errors import ClearanceGrantError
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_REASON = "granting classified read for case batch review"
_AUDIT = SimpleNamespace(service="test", instance_id="t0")


def _user() -> CurrentUser:
    return CurrentUser(
        user_id=uuid4(),
        username="op",
        role=SystemUserRole.ADMIN,
        effective_scopes=frozenset({"admin:clearance"}),
        token_expires_at=None,
    )


def _page(*, include_total: bool = False, limit: int = 50) -> CursorParams:
    return CursorParams(offset=0, limit=limit, include_total=include_total)


async def _seed(storage: BaseRepository, *, grantee, scope=ClearanceScope.READ_CLASSIFIED):
    base = datetime.now(tz=UTC)
    return await storage.grant_clearance(
        grantee_user_id=grantee,
        granter_user_id=uuid4(),
        scope=scope,
        reason=_REASON,
        expires_at=base + timedelta(days=30),
        service="test",
        instance_id="t0",
    )


async def test_grant_then_get_roundtrip(storage: BaseRepository) -> None:
    grantee = uuid4()
    body = ClearanceGrantRequest(
        user_id=grantee,
        scope=ClearanceScope.READ_RESTRICTED,
        reason=_REASON,
        expires_at=datetime.now(tz=UTC) + timedelta(days=10),
    )
    created = await clearance_grant(body, _user(), storage, _AUDIT)  # type: ignore[arg-type]
    assert created.user_id == grantee
    assert created.active is True
    assert created.reason == _REASON

    fetched = await clearance_get_grant(created.grant_id, _user(), storage)
    assert fetched.grant_id == created.grant_id
    assert fetched.scope == ClearanceScope.READ_RESTRICTED


async def test_grant_rejects_over_90_day_expiry(storage: BaseRepository) -> None:
    body = ClearanceGrantRequest(
        user_id=uuid4(),
        scope=ClearanceScope.READ_CLASSIFIED,
        reason=_REASON,
        expires_at=datetime.now(tz=UTC) + timedelta(days=120),
    )
    with pytest.raises(UnprocessableError):
        await clearance_grant(body, _user(), storage, _AUDIT)  # type: ignore[arg-type]


async def test_get_missing_is_404(storage: BaseRepository) -> None:
    with pytest.raises(ResourceNotFound):
        await clearance_get_grant(uuid4(), _user(), storage)


async def test_list_filters_and_active_only(storage: BaseRepository) -> None:
    alice, bob = uuid4(), uuid4()
    await _seed(storage, grantee=alice)
    revoked = await _seed(storage, grantee=bob)
    await storage.revoke_clearance(
        grant_id=revoked.id,
        revoker_user_id=uuid4(),
        reason="no longer needed for the investigation",
        service="test",
        instance_id="t0",
    )

    all_grants = await clearance_list_grants(_user(), storage, _page(include_total=True))
    assert len(all_grants.items) == 2
    assert all_grants.estimated_total == 2

    active = await clearance_list_grants(_user(), storage, _page(), active_only=1)
    active_ids = {g.grant_id for g in active.items}
    assert revoked.id not in active_ids
    assert all(g.active for g in active.items)

    by_user = await clearance_list_grants(_user(), storage, _page(), user_id=alice)
    assert {g.user_id for g in by_user.items} == {alice}


async def test_list_paginates(storage: BaseRepository) -> None:
    for _ in range(3):
        await _seed(storage, grantee=uuid4())
    first = await clearance_list_grants(_user(), storage, _page(limit=2))
    assert len(first.items) == 2
    assert first.next_cursor is not None


async def test_revoke_happy_and_missing(storage: BaseRepository) -> None:
    grant = await _seed(storage, grantee=uuid4())
    accepted = await clearance_revoke_grant(
        grant.id,
        ClearanceRevokeRequest(revocation_reason="access no longer required here"),
        _user(),
        storage,
        _AUDIT,  # type: ignore[arg-type]
    )
    assert accepted.applied is True
    assert accepted.event_id == grant.id

    with pytest.raises(ResourceNotFound):
        await clearance_revoke_grant(
            uuid4(),
            ClearanceRevokeRequest(revocation_reason="grant does not exist at all"),
            _user(),
            storage,
            _AUDIT,  # type: ignore[arg-type]
        )


async def test_revoke_already_expired_is_422(
    storage: BaseRepository, now: datetime
) -> None:
    # Seed a grant that lapsed in the past (fixture ``now`` is well before wall
    # clock): granted_at/expires_at both in 2026-05, expiry 1h out.
    grant = await storage.grant_clearance(
        grantee_user_id=uuid4(),
        granter_user_id=uuid4(),
        scope=ClearanceScope.READ_CLASSIFIED,
        reason=_REASON,
        expires_at=now + timedelta(hours=1),
        now=now,
        service="test",
        instance_id="t0",
    )
    with pytest.raises(UnprocessableError):
        await clearance_revoke_grant(
            grant.id,
            ClearanceRevokeRequest(revocation_reason="revoke after the grant lapsed"),
            _user(),
            storage,
            _AUDIT,  # type: ignore[arg-type]
        )
