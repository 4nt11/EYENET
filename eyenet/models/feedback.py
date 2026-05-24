"""FeedbackPairTable — operator-confirmed SAME/DIFF-author pairs (M8).

Auto-populated by `eyenet linkage confirm` (ground_truth="same") and
`eyenet linkage reject` (ground_truth="diff"). The Verifier calibration
grid (M8+) reads this table to compute per-method AUC against operator
ground truth — replacing M5's role-label-only `rutify_labels.toml` for
pair-based verification.

Colocated with `linkage` in the PROFILES store so the FK to LinkageTable
resolves natively (PLAN §5.2: cross-store FKs are forbidden).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlmodel import Field, SQLModel

from ._base import new_uuid7

FeedbackGroundTruth = Literal["same", "diff"]


class FeedbackPairTable(SQLModel, table=True):
    __tablename__ = "feedback_pair"
    __table_args__ = (
        CheckConstraint("actor_a_id < actor_b_id", name="feedback_pair_ordered"),
        CheckConstraint(
            "ground_truth IN ('same', 'diff')",
            name="feedback_pair_ground_truth",
        ),
        UniqueConstraint("linkage_id", name="uq_feedback_pair_linkage"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    linkage_id: UUID = Field(foreign_key="linkage.id", index=True)
    actor_a_id: UUID = Field(index=True)
    actor_b_id: UUID = Field(index=True)
    ground_truth: str = Field(index=True)
    decided_by: str
    decided_at: datetime
    notes: str | None = None


__all__ = ["FeedbackGroundTruth", "FeedbackPairTable"]
