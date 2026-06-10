# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct storage-mixin tests for ClearanceMixin (grant/revoke/expire/active).

The clearance-grant surface is the authorization backbone for non-NORMAL
file-access gating (the PHASE-6 layer PHASE-5 prepares). Exercised here against
an in-memory ``BaseRepository`` via the factory (CLAUDE.md §2.3 Rule 2),
crediting the grant/revoke/expire-due/active branches the HTTP layer cannot
trace.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from eyenet.contracts.enums import ClearanceScope
from eyenet.storage.errors import MAX_GRANT_DURATION, ClearanceGrantError
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
_REASON = "operator-supplied justification for the grant"


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _grant(
    storage: BaseRepository,
    *,
    grantee=None,
    scope: ClearanceScope = ClearanceScope.READ_RESTRICTED,
    expires_at: datetime | None = None,
    now: datetime = _NOW,
):
    return await storage.grant_clearance(
        grantee_user_id=grantee or uuid4(),
        granter_user_id=uuid4(),
        scope=scope,
        reason=_REASON,
        expires_at=expires_at or (now + timedelta(days=7)),
        now=now,
        service="test",
        instance_id="t0",
    )


async def test_grant_then_active_and_effective(storage: BaseRepository) -> None:
    grantee = uuid4()
    row = await _grant(storage, grantee=grantee)
    active = await storage.active_clearance_grants_for(grantee, now=_NOW)
    assert [g.id for g in active] == [row.id]
    scopes = await storage.effective_clearance_scopes(grantee, now=_NOW)
    assert scopes == frozenset({ClearanceScope.READ_RESTRICTED})


async def test_grant_expires_in_past_is_rejected(storage: BaseRepository) -> None:
    with pytest.raises(ClearanceGrantError, match="strictly after"):
        await _grant(storage, expires_at=_NOW - timedelta(seconds=1))


async def test_grant_over_cap_is_rejected(storage: BaseRepository) -> None:
    with pytest.raises(ClearanceGrantError, match="90-day cap"):
        await _grant(storage, expires_at=_NOW + MAX_GRANT_DURATION + timedelta(days=1))


async def test_grant_short_reason_is_rejected(storage: BaseRepository) -> None:
    with pytest.raises(ClearanceGrantError, match="16 characters"):
        await storage.grant_clearance(
            grantee_user_id=uuid4(),
            granter_user_id=uuid4(),
            scope=ClearanceScope.READ_RESTRICTED,
            reason="short",
            expires_at=_NOW + timedelta(days=1),
            now=_NOW,
            service="test",
            instance_id="t0",
        )


async def test_revoke_marks_revoked_and_drops_from_active(storage: BaseRepository) -> None:
    grantee = uuid4()
    row = await _grant(storage, grantee=grantee)
    revoked = await storage.revoke_clearance(
        grant_id=row.id,
        revoker_user_id=uuid4(),
        reason="revoking after the investigation closed",
        now=_NOW + timedelta(hours=1),
        service="test",
        instance_id="t0",
    )
    assert revoked.revoked_at is not None
    assert await storage.active_clearance_grants_for(grantee, now=_NOW + timedelta(hours=2)) == []


async def test_revoke_is_idempotent(storage: BaseRepository) -> None:
    row = await _grant(storage)
    first = await storage.revoke_clearance(
        grant_id=row.id,
        revoker_user_id=uuid4(),
        reason="first revoke of this clearance grant",
        now=_NOW + timedelta(hours=1),
        service="test",
        instance_id="t0",
    )
    second = await storage.revoke_clearance(
        grant_id=row.id,
        revoker_user_id=uuid4(),
        reason="second revoke should be a no-op idempotent",
        now=_NOW + timedelta(hours=2),
        service="test",
        instance_id="t0",
    )
    assert first.revoked_at == second.revoked_at


async def test_revoke_missing_grant_raises(storage: BaseRepository) -> None:
    with pytest.raises(ClearanceGrantError, match="not found"):
        await storage.revoke_clearance(
            grant_id=uuid4(),
            revoker_user_id=uuid4(),
            reason="revoking a grant that does not exist",
            now=_NOW,
            service="test",
            instance_id="t0",
        )


async def test_revoke_already_expired_raises(storage: BaseRepository) -> None:
    row = await _grant(storage, expires_at=_NOW + timedelta(hours=1))
    with pytest.raises(ClearanceGrantError, match="already expired"):
        await storage.revoke_clearance(
            grant_id=row.id,
            revoker_user_id=uuid4(),
            reason="revoking after it already expired naturally",
            now=_NOW + timedelta(hours=2),
            service="test",
            instance_id="t0",
        )


async def test_expire_due_emits_once_then_idempotent(storage: BaseRepository) -> None:
    row = await _grant(storage, expires_at=_NOW + timedelta(hours=1))
    cutoff = _NOW + timedelta(hours=2)
    first = await storage.expire_due_clearances(now=cutoff, service="test", instance_id="t0")
    assert row.id in first
    # Second sweep: the CLEARANCE_EXPIRED audit row already exists → not re-emitted.
    second = await storage.expire_due_clearances(now=cutoff, service="test", instance_id="t0")
    assert row.id not in second
