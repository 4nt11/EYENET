# SPDX-License-Identifier: AGPL-3.0-or-later
"""LinkagesMixin — proposed → suspected/confirmed/rejected state machine."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from opentelemetry import trace
from sqlalchemy import func
from sqlmodel import col, select

from eyenet.contracts.attribution import LinkageRow
from eyenet.contracts.enums import LinkageState
from eyenet.models.linkage import LinkageTable

from ._helpers import safe_session

_tracer = trace.get_tracer("eyenet.storage.sqlmodel_repo.linkages")

_LEGAL_TRANSITIONS: dict[LinkageState, frozenset[LinkageState]] = {
    LinkageState.PROPOSED: frozenset(
        {
            LinkageState.SUSPECTED,
            LinkageState.CONFIRMED,
            LinkageState.REJECTED,
            LinkageState.SUPERSEDED,
        }
    ),
    LinkageState.SUSPECTED: frozenset({LinkageState.CONFIRMED, LinkageState.REJECTED}),
    LinkageState.CONFIRMED: frozenset(),
    LinkageState.REJECTED: frozenset(),
    LinkageState.SUPERSEDED: frozenset(),
}


def _sorted_pair(a: UUID, b: UUID) -> tuple[UUID, UUID]:
    return (a, b) if a < b else (b, a)


def _row_to_contract(row: LinkageTable) -> LinkageRow:
    return LinkageRow(
        id=row.id,
        actor_a_id=row.actor_a_id,
        actor_b_id=row.actor_b_id,
        state=row.state,
        method=row.method,
        score=row.score,
        evidence=dict(row.evidence),
        proposed_at=row.proposed_at.replace(tzinfo=UTC)
        if row.proposed_at.tzinfo is None
        else row.proposed_at,
        decided_at=row.decided_at.replace(tzinfo=UTC)
        if row.decided_at is not None and row.decided_at.tzinfo is None
        else row.decided_at,
        decided_by=row.decided_by,
        notes=row.notes,
    )


class LinkagesMixin:
    async def insert_proposed_linkage(
        self,
        actor_a: UUID,
        actor_b: UUID,
        method: str,
        score: float,
        evidence: dict[str, Any],
        *,
        linkage_id: UUID | None = None,
    ) -> LinkageRow:
        a, b = _sorted_pair(actor_a, actor_b)
        now = datetime.now(tz=UTC)
        with _tracer.start_as_current_span(
            "storage.linkages.insert_proposed",
            attributes={
                "linkage.method": method,
                "linkage.score": score,
                "actor.a.id": str(a),
                "actor.b.id": str(b),
            },
        ):
            async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
                result = await session.exec(
                    select(LinkageTable).where(
                        col(LinkageTable.actor_a_id) == a,
                        col(LinkageTable.actor_b_id) == b,
                        col(LinkageTable.method) == method,
                        col(LinkageTable.state) == LinkageState.PROPOSED,
                    )
                )
                existing = result.first()
                if existing is None:
                    table_kwargs: dict[str, Any] = {
                        "actor_a_id": a,
                        "actor_b_id": b,
                        "state": LinkageState.PROPOSED,
                        "method": method,
                        "score": score,
                        "evidence": evidence,
                        "proposed_at": now,
                    }
                    if linkage_id is not None:
                        table_kwargs["id"] = linkage_id
                    row = LinkageTable(**table_kwargs)
                    session.add(row)
                    await session.commit()
                    await session.refresh(row)
                    return _row_to_contract(row)
                existing.score = max(existing.score, score)
                existing.evidence = evidence
                session.add(existing)
                await session.commit()
                await session.refresh(existing)
                return _row_to_contract(existing)

    async def transition_linkage(
        self,
        linkage_id: UUID,
        new_state: object,
        decided_by: str,
        notes: str | None = None,
    ) -> LinkageRow:
        target = LinkageState(str(new_state))
        now = datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(LinkageTable, linkage_id)
            if row is None:
                raise ValueError(f"linkage {linkage_id} not found")
            allowed = _LEGAL_TRANSITIONS.get(row.state, frozenset())
            if target not in allowed:
                raise ValueError(
                    f"cannot transition {row.state} → {target}; "
                    f"legal targets: {sorted(s.value for s in allowed) or 'none (terminal)'}"
                )
            row.state = target
            row.decided_at = now
            row.decided_by = decided_by
            row.notes = notes
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _row_to_contract(row)

    async def get_linkage(self, linkage_id: UUID) -> LinkageRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(LinkageTable, linkage_id)
            return _row_to_contract(row) if row is not None else None

    def _linkage_filters(
        self,
        stmt: Any,
        *,
        actor_id: UUID | None,
        state: object | None,
        method: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> Any:
        """Apply the shared WHERE clauses for list/count (M9.F2)."""
        if actor_id is not None:
            stmt = stmt.where(
                (col(LinkageTable.actor_a_id) == actor_id)
                | (col(LinkageTable.actor_b_id) == actor_id)
            )
        if state is not None:
            stmt = stmt.where(col(LinkageTable.state) == LinkageState(str(state)))
        if method is not None:
            stmt = stmt.where(col(LinkageTable.method) == method)
        if since is not None:
            stmt = stmt.where(col(LinkageTable.proposed_at) >= since)
        if until is not None:
            stmt = stmt.where(col(LinkageTable.proposed_at) < until)
        return stmt

    async def list_linkages(
        self,
        actor_id: UUID | None = None,
        state: object | None = None,
        limit: int = 100,
        offset: int = 0,
        *,
        method: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[object]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = self._linkage_filters(
                select(LinkageTable),
                actor_id=actor_id,
                state=state,
                method=method,
                since=since,
                until=until,
            )
            stmt = stmt.order_by(col(LinkageTable.proposed_at).desc()).offset(offset).limit(limit)
            result = await session.exec(stmt)
            rows = list(result)
        return [_row_to_contract(r) for r in rows]

    async def count_linkages(
        self,
        actor_id: UUID | None = None,
        state: object | None = None,
        *,
        method: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int:
        """Count linkages matching the same filters as list_linkages (M9.F2)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = self._linkage_filters(
                select(func.count()).select_from(LinkageTable),
                actor_id=actor_id,
                state=state,
                method=method,
                since=since,
                until=until,
            )
            result = await session.exec(stmt)
            return int(result.one())

    async def confirmed_linkage_pairs(self) -> list[tuple[UUID, UUID]]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(LinkageTable).where(col(LinkageTable.state) == LinkageState.CONFIRMED)
            )
            rows = list(result)
        return [(r.actor_a_id, r.actor_b_id) for r in rows]


__all__ = ["LinkagesMixin"]
