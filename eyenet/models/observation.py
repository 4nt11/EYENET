"""ObservationTable — see contracts/observation.py.

Hot-path index `(actor_id, primitive_name, observed_at DESC)` lives here.

Sensitivity columns (API_PLAN §4.7 / §4.9):
- `classifier_tier`: set by the classifier chain at ingest; immutable at app layer.
- `operator_tier_override`: nullable; if set, must rank >= classifier_tier
  (monotone-up). Storage CHECK enforces — see `_TIER_MONOTONE_CK`.

Effective tier is `COALESCE(operator_tier_override, classifier_tier)`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, Index
from sqlmodel import Column, Field, SQLModel

from eyenet.contracts.enums import SensitivityTier, ValueKind

from ._base import new_uuid7

# Reusable monotonicity CHECK: operator_tier_override (if set) must have rank
# >= classifier_tier. SQLite has no enum-to-int builtin, so we express rank
# via CASE. Used on both ObservationTable and AttachmentTable.
#
# SQLAlchemy persists Python Enum members by NAME (uppercase), not VALUE, so
# the CASE labels must match the enum member names — not the lowercase wire
# strings. If this CHECK is ever copy-pasted into a place that compares the
# wire form, change the case constants accordingly.
_TIER_RANK = "CASE {col} WHEN 'NORMAL' THEN 0 WHEN 'RESTRICTED' THEN 1 WHEN 'CLASSIFIED' THEN 2 END"
TIER_MONOTONE_CK = (
    "operator_tier_override IS NULL OR "
    f"({_TIER_RANK.format(col='operator_tier_override')}) >= "
    f"({_TIER_RANK.format(col='classifier_tier')})"
)


class ObservationTable(SQLModel, table=True):
    __tablename__ = "observation"
    __table_args__ = (
        Index(
            "ix_observation_actor_primitive_observed",
            "actor_id",
            "primitive_name",
            "observed_at",
        ),
        Index(
            "ix_observation_tier",
            "classifier_tier",
            "operator_tier_override",
        ),
        CheckConstraint(TIER_MONOTONE_CK, name="ck_observation_tier_monotone"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    # Cross-store reference (actor lives in messages.db) — indexed UUID, no FK.
    actor_id: UUID = Field(index=True)
    evidence_ref: str | None = Field(default=None, index=True)
    primitive_namespace: str = Field(index=True)
    primitive_name: str
    primitive_version: str
    value_kind: ValueKind
    value_hash: str | None = Field(default=None, index=True)
    value_numeric: float | None = None
    value_enum: str | None = None
    value_array: list[str] | None = Field(default=None, sa_column=Column(JSON))
    value_array_numeric: list[float] | None = Field(default=None, sa_column=Column(JSON))
    window_start: datetime | None = None
    window_end: datetime | None = None
    observed_at: datetime
    sensor_instance: str
    classifier_tier: SensitivityTier = Field(default=SensitivityTier.NORMAL)
    operator_tier_override: SensitivityTier | None = None


__all__ = ["TIER_MONOTONE_CK", "ObservationTable"]
