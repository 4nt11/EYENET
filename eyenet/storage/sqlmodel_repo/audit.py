# SPDX-License-Identifier: AGPL-3.0-or-later
"""AuditMixin — generic audit-log append + read.

The hash-chained ``BEGIN IMMEDIATE`` write path is dialect-specific
(SQLite uses ``BEGIN IMMEDIATE`` on a raw DBAPI cursor; Postgres uses
``SERIALIZABLE``; MySQL uses ``LOCK TABLES`` or ``SELECT ... FOR UPDATE``).
The generic mixin delegates to ``_append_audit_locked`` which subclasses
override. Reading the chain (``all_audit``) is dialect-agnostic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import String, cast, func, text
from sqlmodel import col, select

from eyenet.contracts.audit import AuditLogRow
from eyenet.models import AuditLogTable

from ._helpers import safe_session


def _audit_filters(
    stmt: Any,
    *,
    since: datetime | None,
    until: datetime | None,
    user: UUID | None,
    subject: str | None,
    subject_id: UUID | None,
) -> Any:
    """Shared WHERE clauses for the audit list/count (M9.F4).

    ``subject`` filters the domain ``event`` column — the API renames
    ``event`` -> ``subject`` (see AuditRow). ``subject_id`` filters the audited
    row's identity (e.g. a case_id), giving a per-subject trail off the
    ``ix_audit_subject`` index. ``user`` filters ``system_user_id``;
    ``since``/``until`` bound ``at`` (half-open).
    """
    if since is not None:
        stmt = stmt.where(col(AuditLogTable.at) >= since)
    if until is not None:
        stmt = stmt.where(col(AuditLogTable.at) < until)
    if user is not None:
        # Audit rows are raw-inserted with the dashed UUID string (the
        # hash-chain write path bypasses the column's UUID type), so compare
        # against the stored TEXT form rather than the ORM's binary encoding.
        stmt = stmt.where(cast(col(AuditLogTable.system_user_id), String) == str(user))
    if subject is not None:
        stmt = stmt.where(col(AuditLogTable.event) == subject)
    if subject_id is not None:
        stmt = stmt.where(cast(col(AuditLogTable.subject_id), String) == str(subject_id))
    return stmt


class AuditMixin:
    async def append_audit(self, row_data: dict[str, Any]) -> AuditLogRow:
        return await self._append_audit_locked(row_data)

    async def all_audit(self) -> list[AuditLogRow]:
        async with safe_session(self._audit_session_factory) as session:  # type: ignore[attr-defined]
            # Order by SQLite's implicit rowid (= INSERT-commit order under
            # the BEGIN IMMEDIATE write path). MySQL/Postgres equivalents
            # use a monotonic id column when this mixin gets non-SQLite
            # subclasses.
            result = await session.exec(select(AuditLogTable).order_by(text("rowid ASC")))
            tables = result.all()
            rows: list[AuditLogRow] = []
            for t in tables:
                data = t.model_dump()
                if data["at"].tzinfo is None:
                    data["at"] = data["at"].replace(tzinfo=UTC)
                rows.append(AuditLogRow.model_validate(data))
            return rows

    async def list_audit(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        user: UUID | None = None,
        subject: str | None = None,
        subject_id: UUID | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[object]:
        """Filtered, paginated audit rows, newest-first (M9.F4).

        Returns AuditLogRow contracts (detached-safe). ``all_audit`` remains
        the full-chain reader for verification; this is the browse surface.
        """
        async with safe_session(self._audit_session_factory) as session:  # type: ignore[attr-defined]
            stmt = _audit_filters(
                select(AuditLogTable),
                since=since,
                until=until,
                user=user,
                subject=subject,
                subject_id=subject_id,
            )
            stmt = (
                stmt.order_by(col(AuditLogTable.at).desc())
                .order_by(col(AuditLogTable.id).desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.exec(stmt)
            rows: list[object] = []
            for t in result.all():
                data = t.model_dump()
                if data["at"].tzinfo is None:
                    data["at"] = data["at"].replace(tzinfo=UTC)
                rows.append(AuditLogRow.model_validate(data))
            return rows

    async def count_audit(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        user: UUID | None = None,
        subject: str | None = None,
        subject_id: UUID | None = None,
    ) -> int:
        """Count audit rows matching the same filters as list_audit (M9.F4)."""
        async with safe_session(self._audit_session_factory) as session:  # type: ignore[attr-defined]
            stmt = _audit_filters(
                select(func.count()).select_from(AuditLogTable),
                since=since,
                until=until,
                user=user,
                subject=subject,
                subject_id=subject_id,
            )
            result = await session.exec(stmt)
            return int(result.one())

    async def _append_audit_locked(  # pragma: no cover — overridden
        self,
        row_data: dict[str, Any],
    ) -> AuditLogRow:
        """Dialect-specific hash-chained append. Subclasses MUST override."""

        raise NotImplementedError(
            "_append_audit_locked is dialect-specific; "
            "the concrete backend repository must override it."
        )


__all__ = ["AuditMixin"]
