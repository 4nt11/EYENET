"""GroupAccessArtifactTable (MODELS §2.24, M9.C6).

Records a known way to access a Group or a GroupCandidate — public handle,
invite link, QR code, direct invite, paid subscription tier, access-blocked
state. One-to-many: a single Group commonly carries multiple artifacts.

Cross-platform: the ``kind`` enum is platform-neutral; per-platform quirks
(invite limits, federation servers, etc.) ride in ``details`` JSON.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, Column, Index
from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import ArtifactSubjectKind, ArtifactValidationState, GroupAccessKind

from ._base import new_uuid7


class GroupAccessArtifactTable(SQLModel, table=True):
    """`group_access_artifact` — known access vector for a group/candidate (MODELS §2.24)."""

    __tablename__ = "group_access_artifact"
    __table_args__ = (
        # Discriminated union: exactly one of (group_id, candidate_id) populated.
        CheckConstraint(
            "(group_id IS NOT NULL) <> (candidate_id IS NOT NULL)",
            name="ck_access_artifact_xor_subject",
        ),
        CheckConstraint(
            "subject_kind IN ('GROUP','CANDIDATE')",
            name="ck_access_artifact_subject_kind",
        ),
        CheckConstraint(
            "(subject_kind = 'GROUP' AND group_id IS NOT NULL) "
            "OR (subject_kind = 'CANDIDATE' AND candidate_id IS NOT NULL)",
            name="ck_access_artifact_subject_fk_paired",
        ),
        CheckConstraint(
            "kind IN ('PUBLIC_IDENTIFIER','INVITE_LINK','QR_CODE','DIRECT_INVITE',"
            "'PAID_SUBSCRIPTION','ACCESS_BLOCKED','RESTRICTED_OTHER')",
            name="ck_access_artifact_kind",
        ),
        CheckConstraint(
            "validation_state IN ('UNVERIFIED','VALID','EXPIRED','REVOKED',"
            "'USAGE_EXHAUSTED','BLOCKED_FOR_OUR_IDENTITY','UNKNOWN_FAILURE')",
            name="ck_access_artifact_validation_state",
        ),
        Index("ix_access_artifact_group_state_kind", "group_id", "validation_state", "kind"),
        Index(
            "ix_access_artifact_candidate_state_kind",
            "candidate_id",
            "validation_state",
            "kind",
        ),
        Index("ix_access_artifact_value_kind", "value", "kind"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    subject_kind: ArtifactSubjectKind
    group_id: UUID | None = Field(default=None, foreign_key="group_.id")
    candidate_id: UUID | None = Field(default=None, foreign_key="group_candidate.id")
    kind: GroupAccessKind
    value: str | None = Field(default=None, max_length=1024)
    details: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    discovered_via_mention_id: UUID | None = Field(
        default=None,
        foreign_key="group_candidate_mention.id",
    )
    discovered_at_ingest: datetime
    last_validated_at: datetime | None = None
    validation_state: ArtifactValidationState = ArtifactValidationState.UNVERIFIED
    requires_admin_approval: bool = False
    expires_at: datetime | None = None


__all__ = ["GroupAccessArtifactTable"]
