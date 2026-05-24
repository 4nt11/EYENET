"""Feedback-pair contracts (M8 — operator ground truth for the Verifier grid).

Persisted shape only; never on the bus. Mirrors the LinkageRow / LinkageTable
split — Pydantic ``*Row`` for migrations + storage-boundary validation, the
SQLModel ``*Table`` in ``eyenet.models.feedback`` for SQLite I/O. Surface = db.

A ``FeedbackPair`` row records one operator decision on a candidate linkage:
``ground_truth="same"`` for ``eyenet linkage confirm``, ``"diff"`` for
``reject``. ``suspect`` writes no row — it's still ambiguous.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator

from ._base import DbRowBase

FeedbackGroundTruth = Literal["same", "diff"]


def _ordered_pair(a: UUID, b: UUID) -> tuple[UUID, UUID]:
    """Return `(a, b)` with `a < b`. Mirrors the LinkageRow invariant."""

    return (a, b) if a < b else (b, a)


class FeedbackPairRow(DbRowBase):
    """Persisted operator-confirmed pair (MODELS §M8 / new).

    Invariant: ``actor_a_id < actor_b_id`` enforced at both the contract layer
    (this validator) and the DB layer (``feedback_pair_ordered`` CHECK). The
    ``linkage_id`` FK targets the originating ``Linkage`` row (PROFILES store
    colocation lets the FK resolve natively — see PLAN §5.2).
    """

    linkage_id: UUID
    actor_a_id: UUID
    actor_b_id: UUID
    ground_truth: FeedbackGroundTruth
    decided_by: str
    decided_at: datetime
    notes: str | None = None

    @model_validator(mode="after")
    def _enforce_pair_order(self) -> Self:
        if not self.actor_a_id < self.actor_b_id:
            raise ValueError(
                "FeedbackPairRow requires actor_a_id < actor_b_id; "
                "use FeedbackPairRow.from_pair(a, b, ...) to auto-sort"
            )
        return self

    @classmethod
    def from_pair(
        cls,
        a: UUID,
        b: UUID,
        *,
        linkage_id: UUID,
        ground_truth: FeedbackGroundTruth,
        decided_by: str,
        decided_at: datetime,
        notes: str | None = None,
    ) -> Self:
        ordered_a, ordered_b = _ordered_pair(a, b)
        return cls(
            linkage_id=linkage_id,
            actor_a_id=ordered_a,
            actor_b_id=ordered_b,
            ground_truth=ground_truth,
            decided_by=decided_by,
            decided_at=decided_at,
            notes=notes,
        )


__all__ = ["FeedbackGroundTruth", "FeedbackPairRow"]
