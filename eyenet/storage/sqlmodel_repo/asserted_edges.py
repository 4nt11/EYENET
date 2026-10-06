# SPDX-License-Identifier: AGPL-3.0-or-later
"""AssertedEdgesMixin — durable, audited operator-mapped graph edges (§10.4).

A mapped edge is operator-grade evidence: `assert_edge` / `retract_edge` persist
and AUDIT (GRAPH_EDGE_ASSERTED / GRAPH_EDGE_RETRACTED), soft-delete on retract.
`list_asserted_edges_for` feeds the induced subgraph (active edges with BOTH
endpoints in the node set). Dialect-free (generic SELECT/add); no backend override.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import col, select

from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.models.asserted_edge import AssertedEdgeTable
from eyenet.storage.errors import AssertedEdgeError

from ._helpers import audit_or_warn, build_audit_row, safe_session

_MIN_REASON_LEN = 3


class AssertedEdgesMixin:
    async def assert_edge(
        self,
        *,
        src_type: str,
        src_id: UUID,
        dst_type: str,
        dst_id: UUID,
        kind: str,
        reason: str,
        created_by_user_id: UUID,
        service: str,
        instance_id: str,
        now: datetime | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> object:
        """Create (or return the existing active) operator-asserted edge. Audited.

        Idempotent on (src, dst, kind) among active rows — mapping the same edge
        twice returns the first. Returns the AssertedEdgeTable row (type-erased).
        """
        if len(reason.strip()) < _MIN_REASON_LEN:
            raise AssertedEdgeError("assert_edge reason must be non-trivial")
        at = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            existing = (
                await session.exec(
                    select(AssertedEdgeTable).where(
                        AssertedEdgeTable.src_type == src_type,
                        AssertedEdgeTable.src_id == src_id,
                        AssertedEdgeTable.dst_type == dst_type,
                        AssertedEdgeTable.dst_id == dst_id,
                        AssertedEdgeTable.kind == kind,
                        col(AssertedEdgeTable.removed_at).is_(None),
                    )
                )
            ).first()
            if existing is not None:
                return existing
            row = AssertedEdgeTable(
                src_type=src_type,
                src_id=src_id,
                dst_type=dst_type,
                dst_id=dst_id,
                kind=kind,
                reason=reason,
                created_by_user_id=created_by_user_id,
                created_at=at,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            edge_id = row.id
        await audit_or_warn(
            self,  # type: ignore[arg-type]
            build_audit_row(
                event=AuditSubject.GRAPH_EDGE_ASSERTED,
                actor=created_by_user_id,
                subject_kind="asserted_edge",
                subject_id=edge_id,
                payload={
                    "src": f"{src_type}:{src_id}",
                    "dst": f"{dst_type}:{dst_id}",
                    "kind": kind,
                    "reason": reason,
                },
                at=at,
                service=service,
                instance_id=instance_id,
                trace_id=trace_id,
                span_id=span_id,
            ),
            helper="assert_edge",
            domain_id=edge_id,
        )
        return row

    async def retract_edge(
        self,
        *,
        edge_id: UUID,
        removed_by_user_id: UUID,
        reason: str,
        service: str,
        instance_id: str,
        now: datetime | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> bool:
        """Soft-delete an asserted edge (evidence retained). Audited. False if absent."""
        at = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(AssertedEdgeTable, edge_id)
            if row is None or row.removed_at is not None:
                return False
            row.removed_at = at
            row.removed_by_user_id = removed_by_user_id
            row.removal_reason = reason
            session.add(row)
            await session.commit()
        await audit_or_warn(
            self,  # type: ignore[arg-type]
            build_audit_row(
                event=AuditSubject.GRAPH_EDGE_RETRACTED,
                actor=removed_by_user_id,
                subject_kind="asserted_edge",
                subject_id=edge_id,
                payload={"reason": reason},
                at=at,
                service=service,
                instance_id=instance_id,
                trace_id=trace_id,
                span_id=span_id,
            ),
            helper="retract_edge",
            domain_id=edge_id,
        )
        return True

    async def list_asserted_edges_for(self, entity_ids: Collection[UUID]) -> list[object]:
        """Active asserted edges with BOTH endpoints in ``entity_ids`` (induced subgraph)."""
        ids = list(entity_ids)
        if not ids:
            return []
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(AssertedEdgeTable).where(
                    col(AssertedEdgeTable.src_id).in_(ids),
                    col(AssertedEdgeTable.dst_id).in_(ids),
                    col(AssertedEdgeTable.removed_at).is_(None),
                )
            )
            return list(result)


__all__ = ["AssertedEdgesMixin"]
