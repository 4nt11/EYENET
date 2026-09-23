# SPDX-License-Identifier: AGPL-3.0-or-later
"""AnchorsMixin — external-witness anchor records + chain-head reads (§5.9).

Generic ANSI SQL only. Anchor rows live in main.db (a derived log); the audit
head is read from audit.db, the journal head via the existing file-access method.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, text
from sqlmodel import col, select

from eyenet.contracts.anchor import AnchorRow
from eyenet.contracts.audit import GENESIS_PREV_HASH
from eyenet.models import AuditAnchorTable, AuditLogTable

from ._helpers import safe_session


def _row_from_table(table: AuditAnchorTable) -> AnchorRow:
    data = table.model_dump()
    # SQLite drops tz on round-trip; the signed canonical binds the UTC
    # isoformat, so a reader must re-attach UTC to reproduce it.
    at = data.get("anchored_at")
    if isinstance(at, datetime) and at.tzinfo is None:
        data["anchored_at"] = at.replace(tzinfo=UTC)
    return AnchorRow.model_validate(data)


class AnchorsMixin:
    async def audit_head(self) -> str:
        """Hex `self_hash` of the latest audit_log row, or genesis if empty."""
        async with safe_session(self._audit_session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(AuditLogTable).order_by(text("rowid DESC")).limit(1)
            row = (await session.exec(stmt)).first()
            return GENESIS_PREV_HASH if row is None else row.self_hash

    async def latest_anchor_seq(self, deployment_id: UUID) -> int:
        """Highest anchor_seq for the deployment, or -1 when none exist."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(func.max(col(AuditAnchorTable.anchor_seq))).where(
                col(AuditAnchorTable.deployment_id) == deployment_id
            )
            result = (await session.exec(stmt)).one()
            return -1 if result is None else int(result)

    async def record_anchor(
        self,
        *,
        deployment_id: UUID,
        anchor_seq: int,
        anchored_at: datetime,
        audit_head: str,
        journal_head: str,
        signature: str,
    ) -> AnchorRow:
        table = AuditAnchorTable(
            deployment_id=deployment_id,
            anchor_seq=anchor_seq,
            anchored_at=anchored_at,
            audit_head=audit_head,
            journal_head=journal_head,
            signature=signature,
        )
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            session.add(table)
            await session.commit()
            await session.refresh(table)
        return _row_from_table(table)

    def _anchor_window(self, stmt: Any, *, since: datetime | None, until: datetime | None) -> Any:
        if since is not None:
            stmt = stmt.where(col(AuditAnchorTable.anchored_at) >= since)
        if until is not None:
            stmt = stmt.where(col(AuditAnchorTable.anchored_at) <= until)
        return stmt

    async def list_anchors(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[AnchorRow]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = self._anchor_window(select(AuditAnchorTable), since=since, until=until)
            stmt = (
                stmt.order_by(
                    col(AuditAnchorTable.anchored_at).desc(),
                    col(AuditAnchorTable.id).desc(),
                )
                .offset(offset)
                .limit(limit)
            )
            result = await session.exec(stmt)
            return [_row_from_table(r) for r in result]

    async def count_anchors(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = self._anchor_window(
                select(func.count()).select_from(AuditAnchorTable),
                since=since,
                until=until,
            )
            return int((await session.exec(stmt)).one())


__all__ = ["AnchorsMixin"]
