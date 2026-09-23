# SPDX-License-Identifier: AGPL-3.0-or-later
"""ClearanceMixin — grant / revoke / expire_due / active_for / effective_scopes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlmodel import col, select

from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.clearance import SystemUserClearanceGrantRow
from eyenet.contracts.enums import ClearanceScope
from eyenet.models import AuditLogTable
from eyenet.models.clearance import SystemUserClearanceGrantTable
from eyenet.storage.errors import MAX_GRANT_DURATION, ClearanceGrantError

from ._helpers import audit_or_warn, build_audit_row, safe_session

_MIN_REASON_LEN = 16
_SYSTEM_USER_SUBJECT_KIND = "system_user"


def _row_from_table(table: SystemUserClearanceGrantTable) -> SystemUserClearanceGrantRow:
    data = table.model_dump()
    for key in ("granted_at", "expires_at", "revoked_at"):
        val = data.get(key)
        if isinstance(val, datetime) and val.tzinfo is None:
            data[key] = val.replace(tzinfo=UTC)
    return SystemUserClearanceGrantRow.model_validate(data)


class ClearanceMixin:
    async def grant_clearance(
        self,
        *,
        grantee_user_id: UUID,
        granter_user_id: UUID,
        scope: ClearanceScope,
        reason: str,
        expires_at: datetime,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> SystemUserClearanceGrantRow:
        granted_at = now or datetime.now(tz=UTC)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= granted_at:
            raise ClearanceGrantError("expires_at must be strictly after granted_at")
        if expires_at - granted_at > MAX_GRANT_DURATION:
            raise ClearanceGrantError(
                f"grant duration exceeds 90-day cap (got {expires_at - granted_at})"
            )
        if len(reason) < _MIN_REASON_LEN:
            raise ClearanceGrantError("reason must be at least 16 characters")

        table = SystemUserClearanceGrantTable(
            user_id=grantee_user_id,
            scope=scope,
            granted_by_user_id=granter_user_id,
            reason=reason,
            granted_at=granted_at,
            expires_at=expires_at,
        )
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            session.add(table)
            await session.commit()
            await session.refresh(table)

        row = _row_from_table(table)
        await audit_or_warn(
            self,  # type: ignore[arg-type]
            build_audit_row(
                event=AuditSubject.CLEARANCE_GRANTED,
                actor=granter_user_id,
                subject_kind=_SYSTEM_USER_SUBJECT_KIND,
                subject_id=grantee_user_id,
                payload={
                    "grant_id": str(row.id),
                    "scope": scope.value,
                    "expires_at": expires_at.isoformat(),
                    "granted_by_user_id": str(granter_user_id),
                    "reason": reason,
                },
                at=granted_at,
                service=service,
                instance_id=instance_id,
                trace_id=trace_id,
                span_id=span_id,
            ),
            helper="clearance.grant",
            domain_id=row.id,
        )
        return row

    async def revoke_clearance(
        self,
        *,
        grant_id: UUID,
        revoker_user_id: UUID,
        reason: str,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> SystemUserClearanceGrantRow:
        revoked_at = now or datetime.now(tz=UTC)
        if len(reason) < _MIN_REASON_LEN:
            raise ClearanceGrantError("revocation reason must be at least 16 characters")
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(SystemUserClearanceGrantTable, grant_id)
            if table is None:
                raise ClearanceGrantError(f"grant {grant_id} not found")
            if table.revoked_at is not None:
                return _row_from_table(table)
            existing_expires_at = (
                table.expires_at.replace(tzinfo=UTC)
                if table.expires_at.tzinfo is None
                else table.expires_at
            )
            if existing_expires_at <= revoked_at:
                raise ClearanceGrantError(f"grant {grant_id} has already expired")
            table.revoked_at = revoked_at
            table.revoked_by_user_id = revoker_user_id
            table.revocation_reason = reason
            session.add(table)
            await session.commit()
            await session.refresh(table)
            row = _row_from_table(table)

        await audit_or_warn(
            self,  # type: ignore[arg-type]
            build_audit_row(
                event=AuditSubject.CLEARANCE_REVOKED,
                actor=revoker_user_id,
                subject_kind=_SYSTEM_USER_SUBJECT_KIND,
                subject_id=row.user_id,
                payload={
                    "grant_id": str(row.id),
                    "scope": row.scope.value,
                    "revoked_by_user_id": str(revoker_user_id),
                    "revocation_reason": reason,
                },
                at=revoked_at,
                service=service,
                instance_id=instance_id,
                trace_id=trace_id,
                span_id=span_id,
            ),
            helper="clearance.revoke",
            domain_id=row.id,
        )
        return row

    async def expire_due_clearances(
        self,
        *,
        now: datetime | None = None,
        service: str,
        instance_id: str,
    ) -> list[UUID]:
        cutoff = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(SystemUserClearanceGrantTable).where(
                col(SystemUserClearanceGrantTable.expires_at) <= cutoff,
                col(SystemUserClearanceGrantTable.revoked_at).is_(None),
            )
            result = await session.exec(stmt)
            expired = list(result)

        already_emitted = await self._already_expired_grant_ids()
        emitted: list[UUID] = []
        for table in expired:
            row = _row_from_table(table)
            if row.id in already_emitted:
                continue
            await audit_or_warn(
                self,  # type: ignore[arg-type]
                build_audit_row(
                    event=AuditSubject.CLEARANCE_EXPIRED,
                    actor=None,
                    subject_kind=_SYSTEM_USER_SUBJECT_KIND,
                    subject_id=row.user_id,
                    payload={
                        "grant_id": str(row.id),
                        "scope": row.scope.value,
                        "expired_at": row.expires_at.isoformat(),
                    },
                    at=cutoff,
                    service=service,
                    instance_id=instance_id,
                    trace_id=None,
                    span_id=None,
                ),
                helper="clearance.expire_due",
                domain_id=row.id,
            )
            emitted.append(row.id)
        return emitted

    async def _already_expired_grant_ids(self) -> set[UUID]:
        expired: set[UUID] = set()
        async with safe_session(self._audit_session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(AuditLogTable).where(
                col(AuditLogTable.event) == AuditSubject.CLEARANCE_EXPIRED.value
            )
            result = await session.exec(stmt)
            for row in list(result):
                payload: dict[str, Any] = dict(row.payload or {})
                gid = payload.get("grant_id")
                if isinstance(gid, str):
                    try:
                        expired.add(UUID(gid))
                    except ValueError:
                        continue
        return expired

    async def active_clearance_grants_for(
        self,
        user_id: UUID,
        *,
        now: datetime | None = None,
    ) -> list[SystemUserClearanceGrantRow]:
        at = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(SystemUserClearanceGrantTable)
                .where(col(SystemUserClearanceGrantTable.user_id) == user_id)
                .where(col(SystemUserClearanceGrantTable.revoked_at).is_(None))
                .where(col(SystemUserClearanceGrantTable.expires_at) > at)
            )
            result = await session.exec(stmt)
            rows = list(result)
            return [_row_from_table(r) for r in rows]

    async def effective_clearance_scopes(
        self,
        user_id: UUID,
        *,
        now: datetime | None = None,
    ) -> frozenset[ClearanceScope]:
        grants = await self.active_clearance_grants_for(user_id, now=now)
        return frozenset(g.scope for g in grants)

    async def get_clearance_grant(self, grant_id: UUID) -> SystemUserClearanceGrantRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(SystemUserClearanceGrantTable, grant_id)
            return None if table is None else _row_from_table(table)

    def _grant_filters(
        self,
        stmt: Any,
        *,
        user_id: UUID | None,
        scope: ClearanceScope | None,
        active_only: bool,
        at: datetime,
    ) -> Any:
        if user_id is not None:
            stmt = stmt.where(col(SystemUserClearanceGrantTable.user_id) == user_id)
        if scope is not None:
            stmt = stmt.where(col(SystemUserClearanceGrantTable.scope) == scope)
        if active_only:
            stmt = (
                stmt.where(col(SystemUserClearanceGrantTable.revoked_at).is_(None))
                .where(col(SystemUserClearanceGrantTable.expires_at) > at)
                .where(col(SystemUserClearanceGrantTable.granted_at) <= at)
            )
        return stmt

    async def list_clearance_grants(
        self,
        *,
        user_id: UUID | None = None,
        scope: ClearanceScope | None = None,
        active_only: bool = False,
        now: datetime | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[SystemUserClearanceGrantRow]:
        at = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = self._grant_filters(
                select(SystemUserClearanceGrantTable),
                user_id=user_id,
                scope=scope,
                active_only=active_only,
                at=at,
            )
            stmt = (
                stmt.order_by(
                    col(SystemUserClearanceGrantTable.granted_at).desc(),
                    col(SystemUserClearanceGrantTable.id).desc(),
                )
                .offset(offset)
                .limit(limit)
            )
            result = await session.exec(stmt)
            return [_row_from_table(r) for r in result]

    async def count_clearance_grants(
        self,
        *,
        user_id: UUID | None = None,
        scope: ClearanceScope | None = None,
        active_only: bool = False,
        now: datetime | None = None,
    ) -> int:
        at = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = self._grant_filters(
                select(func.count()).select_from(SystemUserClearanceGrantTable),
                user_id=user_id,
                scope=scope,
                active_only=active_only,
                at=at,
            )
            result = await session.exec(stmt)
            return int(result.one())


__all__ = ["ClearanceMixin"]
