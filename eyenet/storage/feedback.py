"""SQLiteFeedbackPairStore — operator-confirmed SAME/DIFF pairs (M8).

Mirrors `SQLiteLinkageStore`'s pair-order invariant. Colocated in the
PROFILES store engine so the linkage_id FK resolves natively (PLAN §5.2).

Storage-boundary type narrowing: the contract layer publishes
``FeedbackPairRow`` (Pydantic); SQLModel ``FeedbackPairTable`` is an
implementation detail of this file. ``_row_to_contract`` converts at the
boundary, same shape as ``SQLiteLinkageStore._row_to_contract``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

import eyenet.models  # noqa: F401 — registers tables on SQLModel.metadata
from eyenet.contracts.feedback import FeedbackGroundTruth, FeedbackPairRow
from eyenet.contracts.storage import FeedbackPairStore
from eyenet.models.feedback import FeedbackPairTable
from eyenet.storage.engines import StoreName, create_all_for

_VALID_GROUND_TRUTHS: frozenset[str] = frozenset({"same", "diff"})


def _sorted_pair(a: UUID, b: UUID) -> tuple[UUID, UUID]:
    return (a, b) if a < b else (b, a)


def _row_to_contract(row: FeedbackPairTable) -> FeedbackPairRow:
    decided_at = row.decided_at
    if decided_at.tzinfo is None:
        decided_at = decided_at.replace(tzinfo=UTC)
    return FeedbackPairRow(
        id=row.id,
        linkage_id=row.linkage_id,
        actor_a_id=row.actor_a_id,
        actor_b_id=row.actor_b_id,
        ground_truth=cast("FeedbackGroundTruth", row.ground_truth),
        decided_by=row.decided_by,
        decided_at=decided_at,
        notes=row.notes,
    )


class SQLiteFeedbackPairStore(FeedbackPairStore):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        create_all_for(StoreName.MAIN, engine)

    async def record(
        self,
        *,
        linkage_id: UUID,
        actor_a: UUID,
        actor_b: UUID,
        ground_truth: str,
        decided_by: str,
        decided_at: datetime,
        notes: str | None = None,
    ) -> FeedbackPairRow:
        if ground_truth not in _VALID_GROUND_TRUTHS:
            raise ValueError(
                f"ground_truth must be one of {sorted(_VALID_GROUND_TRUTHS)}; got {ground_truth!r}"
            )
        a, b = _sorted_pair(actor_a, actor_b)
        with Session(self._engine) as session:
            existing = session.exec(
                select(FeedbackPairTable).where(col(FeedbackPairTable.linkage_id) == linkage_id)
            ).first()
            if existing is not None:
                existing.ground_truth = ground_truth
                existing.decided_by = decided_by
                existing.decided_at = decided_at
                existing.notes = notes
                session.add(existing)
                session.commit()
                session.refresh(existing)
                return _row_to_contract(existing)
            row = FeedbackPairTable(
                linkage_id=linkage_id,
                actor_a_id=a,
                actor_b_id=b,
                ground_truth=ground_truth,
                decided_by=decided_by,
                decided_at=decided_at,
                notes=notes,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return _row_to_contract(row)

    async def get(self, linkage_id: UUID) -> FeedbackPairRow | None:
        with Session(self._engine) as session:
            row = session.exec(
                select(FeedbackPairTable).where(col(FeedbackPairTable.linkage_id) == linkage_id)
            ).first()
        return _row_to_contract(row) if row is not None else None

    async def all_pairs(self) -> list[tuple[UUID, UUID, str]]:
        with Session(self._engine) as session:
            rows = session.exec(select(FeedbackPairTable)).all()
        return [(r.actor_a_id, r.actor_b_id, r.ground_truth) for r in rows]


__all__ = ["SQLiteFeedbackPairStore"]
