"""IdentityTable + IdentityLabelTable + EngagementAuthorizationTable.

Per MODELS §2.13, EngagementAuthorization enforces exactly-one-of
(actor_id, group_id) at the DB layer via a CHECK constraint.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint
from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import (
    ConfidenceTier,
    EngagementScope,
    EngagementSubjectKind,
    IdentityRole,
    IdentityState,
)

from ._base import new_uuid7


class IdentityTable(SQLModel, table=True):
    __tablename__ = "identity"
    __table_args__ = (
        CheckConstraint(
            "role IN ('MONITOR', 'SCOUT', 'QUARANTINE')",
            name="ck_identity_role",
        ),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    name: str = Field(unique=True, index=True)
    source_id: UUID = Field(foreign_key="source.id", index=True)
    session_path: str
    proxy_uri: str | None = None
    cooldown_seconds: int = 21_600
    last_used_at: datetime | None = None
    state: IdentityState = IdentityState.AVAILABLE
    # Discovery-loop role (API_PLAN §4.12). Existing identities default
    # to MONITOR — scouts are explicitly promoted by the
    # CollectorSupervisor (M9.E4) when joining freshly-approved
    # GroupCandidates, and graduate back to MONITOR after a 7-day
    # observation window.
    role: IdentityRole = Field(default=IdentityRole.MONITOR, index=True)
    notes: str | None = None


class IdentityLabelTable(SQLModel, table=True):
    __tablename__ = "identity_label"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    actor_id: UUID = Field(foreign_key="actor.id", index=True)
    label: str = Field(index=True)
    confidence: ConfidenceTier
    applied_by: str
    applied_at: datetime = Field(index=True)
    rationale: str


class EngagementAuthorizationTable(SQLModel, table=True):
    __tablename__ = "engagement_authorization"
    __table_args__ = (
        CheckConstraint(
            "(actor_id IS NOT NULL AND group_id IS NULL) "
            "OR (actor_id IS NULL AND group_id IS NOT NULL)",
            name="engagement_exactly_one_subject",
        ),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    subject_kind: EngagementSubjectKind = Field(index=True)
    actor_id: UUID | None = Field(default=None, foreign_key="actor.id", index=True)
    group_id: UUID | None = Field(default=None, foreign_key="group_.id", index=True)
    authorized_by: str
    authorized_at: datetime
    scope: EngagementScope
    expires_at: datetime | None = None


__all__ = [
    "EngagementAuthorizationTable",
    "IdentityLabelTable",
    "IdentityTable",
]
