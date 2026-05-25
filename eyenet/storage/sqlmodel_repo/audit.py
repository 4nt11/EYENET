# SPDX-License-Identifier: AGPL-3.0-or-later
"""AuditMixin — generic audit-log append + read.

The hash-chained ``BEGIN IMMEDIATE`` write path is dialect-specific
(SQLite uses ``BEGIN IMMEDIATE`` on a raw DBAPI cursor; Postgres uses
``SERIALIZABLE``; MySQL uses ``LOCK TABLES`` or ``SELECT ... FOR UPDATE``).
The generic mixin delegates to ``_append_audit_locked`` which subclasses
override. Reading the chain (``all_audit``) is dialect-agnostic.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

from sqlalchemy import text
from sqlmodel import select

from eyenet.contracts.audit import AuditLogRow
from eyenet.models import AuditLogTable

from ._helpers import safe_session


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
