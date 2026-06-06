"""`Case` — first-class investigation primitive (API_PLAN §4.10, MODELS §2.15).

A case groups evidence (observations / attachments / messages / actors /
personas / linkages) for an investigation. Membership is an m:n junction
(`CaseMemberRow`); collaborators are a parallel m:n (`CaseCollaboratorRow`).

Classified rows are visible ONLY to active case collaborators whose case
holds them as active members (§4.10.4 hybrid access). The case's
`effective_tier` is materialised at the max tier across active members.

Surface: db.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from ._base import DbRowBase
from .enums import (
    AutoJoinPolicy,
    CaseRoleOnCase,
    CaseStatus,
    CaseSubjectKind,
    RedundancyPolicy,
    SensitivityTier,
)


class CaseRow(DbRowBase):
    """Persisted case (API_PLAN §4.10.1, MODELS §2.15).

    The `id` field (from `DbRowBase`) is the case_id wire identifier.
    """

    title: str = Field(min_length=3, max_length=256)
    description: str | None = Field(default=None, max_length=8192)
    status: CaseStatus = CaseStatus.OPEN
    effective_tier: SensitivityTier = SensitivityTier.NORMAL
    created_by_user_id: UUID
    created_at: datetime
    closed_at: datetime | None = None
    closed_by_user_id: UUID | None = None
    close_reason: str | None = Field(default=None, max_length=1024)
    archived_at: datetime | None = None
    archived_by_user_id: UUID | None = None
    archive_reason: str | None = Field(default=None, max_length=1024)
    parent_case_id: UUID | None = Field(
        default=None,
        description="Predecessor case when this row is a successor "
        "created by reopening an archived case (§4.10.3).",
    )
    # -- Discovery-loop policy (API_PLAN §4.12, M9.D4 / Group E fold-in) -------
    seed_root_group_ids: list[UUID] = Field(
        default_factory=list,
        description="Operator-curated initial root groups (depth-0 in the "
        "discovery tree). Mutating emits `case.seed_roots_changed`.",
    )
    redundancy_policy: RedundancyPolicy = RedundancyPolicy.PREFER_SINGLE
    auto_join_policy: AutoJoinPolicy = AutoJoinPolicy.DISABLED
    auto_join_score_threshold: float | None = None


class CaseMemberRow(DbRowBase):
    """An evidence row attached to a case (API_PLAN §4.10.1).

    The `id` field is the member_id. Soft-deleted via `removed_at`; the
    storage layer enforces partial-unique on `(case_id, subject_kind,
    subject_id) WHERE removed_at IS NULL`.

    `subject_id` references rows across all 8 SQLite stores; no SQL FK
    (PLAN §5.2 — cross-store integrity is the storage layer's job).
    """

    case_id: UUID
    subject_kind: CaseSubjectKind
    subject_id: UUID
    added_by_user_id: UUID
    added_at: datetime
    add_reason: str = Field(min_length=16, max_length=1024)
    removed_at: datetime | None = None
    removed_by_user_id: UUID | None = None
    removal_reason: str | None = Field(default=None, max_length=1024)


class CaseCollaboratorRow(DbRowBase):
    """A user authorised to view/edit a case (API_PLAN §4.10.1).

    Role is per-case, distinct from `SystemUserRole`. Soft-revoked via
    `revoked_at`; partial-unique on `(case_id, user_id) WHERE revoked_at
    IS NULL`.
    """

    case_id: UUID
    user_id: UUID
    role_on_case: CaseRoleOnCase
    granted_by_user_id: UUID
    granted_at: datetime
    revoked_at: datetime | None = None
    revoked_by_user_id: UUID | None = None
    revocation_reason: str | None = Field(default=None, max_length=1024)


__all__ = ["CaseCollaboratorRow", "CaseMemberRow", "CaseRow"]
