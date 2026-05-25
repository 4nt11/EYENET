# SPDX-License-Identifier: AGPL-3.0-or-later
"""FeedbackMixin — operator-confirmed SAME/DIFF pairs (M8)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlmodel import col, select

from eyenet.contracts.feedback import FeedbackGroundTruth, FeedbackPairRow
from eyenet.models.feedback import FeedbackPairTable

from ._helpers import safe_session

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


class FeedbackMixin:
    async def record_feedback_pair(
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
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            existing_result = await session.exec(
                select(FeedbackPairTable).where(col(FeedbackPairTable.linkage_id) == linkage_id)
            )
            existing = existing_result.first()
            if existing is not None:
                existing.ground_truth = ground_truth
                existing.decided_by = decided_by
                existing.decided_at = decided_at
                existing.notes = notes
                session.add(existing)
                await session.commit()
                await session.refresh(existing)
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
            await session.commit()
            await session.refresh(row)
            return _row_to_contract(row)

    async def get_feedback_pair(self, linkage_id: UUID) -> FeedbackPairRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(FeedbackPairTable).where(col(FeedbackPairTable.linkage_id) == linkage_id)
            )
            row = result.first()
        return _row_to_contract(row) if row is not None else None

    async def all_feedback_pairs(self) -> list[tuple[UUID, UUID, str]]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(FeedbackPairTable))
            rows = list(result)
        return [(r.actor_a_id, r.actor_b_id, r.ground_truth) for r in rows]


__all__ = ["FeedbackMixin"]
