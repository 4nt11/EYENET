"""SQLiteLinkageStore — repo over LinkageTable.

Enforces the actor_a_id < actor_b_id invariant at write time.
Implements the state machine:
- PROPOSED → {SUSPECTED, CONFIRMED, REJECTED, SUPERSEDED}
- SUSPECTED → {CONFIRMED, REJECTED}

Idempotent on insert: (actor_a, actor_b, method) is unique (uq_linkage_pair_method).
If a PROPOSED row already exists for the pair+method, updates score if higher.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from opentelemetry import trace
from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

import eyenet.models  # noqa: F401 — registers tables on SQLModel.metadata
from eyenet.contracts.attribution import LinkageRow
from eyenet.contracts.enums import LinkageState
from eyenet.contracts.storage import LinkageStore
from eyenet.models.linkage import LinkageTable
from eyenet.storage.engines import StoreName, create_all_for

_tracer = trace.get_tracer("eyenet.storage.linkages")

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


class SQLiteLinkageStore(LinkageStore):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        create_all_for(StoreName.PROFILES, engine)

    async def insert_proposed(
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
        with (
            _tracer.start_as_current_span(
                "storage.linkages.insert_proposed",
                attributes={
                    "linkage.method": method,
                    "linkage.score": score,
                    "actor.a.id": str(a),
                    "actor.b.id": str(b),
                },
            ),
            Session(self._engine) as session,
        ):
            existing = session.exec(
                select(LinkageTable).where(
                    col(LinkageTable.actor_a_id) == a,
                    col(LinkageTable.actor_b_id) == b,
                    col(LinkageTable.method) == method,
                    col(LinkageTable.state) == LinkageState.PROPOSED,
                )
            ).first()
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
                    # Honor the caller's id so the bus envelope's
                    # linkage_id matches the DB row. Mismatch silently
                    # breaks downstream state-machine transitions over
                    # the wire (M8 Verifier debugged this on 2026-05-24).
                    table_kwargs["id"] = linkage_id
                row = LinkageTable(**table_kwargs)
                session.add(row)
                session.commit()
                session.refresh(row)
                return _row_to_contract(row)
            # Update score if higher; evidence always refreshed.
            existing.score = max(existing.score, score)
            existing.evidence = evidence
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return _row_to_contract(existing)

    async def transition(
        self,
        linkage_id: UUID,
        new_state: object,
        decided_by: str,
        notes: str | None = None,
    ) -> LinkageRow:
        target = LinkageState(str(new_state))
        now = datetime.now(tz=UTC)
        with Session(self._engine) as session:
            row = session.get(LinkageTable, linkage_id)
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
            session.commit()
            session.refresh(row)
            return _row_to_contract(row)

    async def get(self, linkage_id: UUID) -> LinkageRow | None:
        with Session(self._engine) as session:
            row = session.get(LinkageTable, linkage_id)
            return _row_to_contract(row) if row is not None else None

    async def list_linkages(
        self,
        actor_id: UUID | None = None,
        state: object | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[object]:  # protocol uses `object` to avoid circular contracts deps
        with Session(self._engine) as session:
            stmt = select(LinkageTable)
            if actor_id is not None:
                stmt = stmt.where(
                    (col(LinkageTable.actor_a_id) == actor_id)
                    | (col(LinkageTable.actor_b_id) == actor_id)
                )
            if state is not None:
                stmt = stmt.where(col(LinkageTable.state) == LinkageState(str(state)))
            stmt = stmt.order_by(col(LinkageTable.proposed_at).desc()).offset(offset).limit(limit)
            rows = session.exec(stmt).all()
        return [_row_to_contract(r) for r in rows]

    async def get_confirmed_pairs(self) -> list[tuple[UUID, UUID]]:
        """Return all (actor_a_id, actor_b_id) pairs in CONFIRMED state.

        Used by PersonaStore.split_actor to recompute connected components.
        """
        with Session(self._engine) as session:
            rows = session.exec(
                select(LinkageTable).where(col(LinkageTable.state) == LinkageState.CONFIRMED)
            ).all()
        return [(r.actor_a_id, r.actor_b_id) for r in rows]


__all__ = ["SQLiteLinkageStore"]
