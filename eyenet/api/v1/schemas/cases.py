"""Case management surfaces — API_PLAN §4.10.

Cases are first-class investigation primitives: a UUID-identified collection
of evidence (observations, attachments, messages, actors, personas, linkages)
with a lifecycle (open → closed → archived), a collaborator roster, an
effective tier monotone-up within an open lifecycle, and a hash-chained audit
trail that turns the legacy `case=APT-29` text convention into a referenceable
entity.

The hybrid access rule (§4.10.4) makes case membership LOAD-BEARING: reading
a `classified` row requires both `read:classified` AND active collaborator
status on at least one case that has the row as an active member.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from ._base import ApiSchema
from .enums import CaseRoleOnCase, CaseStatus, CaseSubjectKind, SensitivityTier

# ── Cases ────────────────────────────────────────────────────────────────


class CaseSummary(ApiSchema):
    """List/index projection of a case (§4.10)."""

    case_id: UUID
    title: str = Field(min_length=4, max_length=256)
    status: CaseStatus
    effective_tier: SensitivityTier
    created_by_user_id: UUID
    created_at: datetime
    member_count: int | None = Field(default=None, ge=0)
    collaborator_count: int | None = Field(default=None, ge=0)


class CaseDetail(CaseSummary):
    """Detail projection — adds description and lifecycle timestamps/reasons."""

    description: str | None = Field(default=None, max_length=8192)
    closed_at: datetime | None = None
    closed_by_user_id: UUID | None = None
    close_reason: str | None = Field(default=None, max_length=1024)
    archived_at: datetime | None = None
    archived_by_user_id: UUID | None = None
    archive_reason: str | None = Field(default=None, max_length=1024)
    parent_case_id: UUID | None = None


class CursorPageCaseSummary(ApiSchema):
    """Cursor-paginated case listing."""

    items: list[CaseSummary] = Field(default_factory=list)
    next_cursor: str | None = None
    estimated_total: int | None = Field(default=None, ge=0)


class CaseCreateRequest(ApiSchema):
    """Body for POST /v1/cases. Creator becomes owner collaborator automatically."""

    title: str = Field(min_length=4, max_length=256)
    description: str | None = Field(default=None, max_length=8192)


class CaseUpdateRequest(ApiSchema):
    """Body for PATCH /v1/cases/{case_id}. Either or both of title/description.

    Rejected by the endpoint when the case's status is not `open` — see §4.10.3.
    """

    title: str | None = Field(default=None, min_length=4, max_length=256)
    description: str | None = Field(default=None, max_length=8192)
    reason: str = Field(min_length=16, max_length=1024)


class CaseCloseRequest(ApiSchema):
    """Body for POST /v1/cases/{case_id}/close. Open → closed (§4.10.3)."""

    close_reason: str = Field(min_length=16, max_length=1024)


class CaseReopenRequest(ApiSchema):
    """Body for POST /v1/cases/{case_id}/reopen.

    Closed → open: caller must own the case OR hold `admin:case`.
    Archived → open: caller must hold `admin:case`; server creates a successor
    case row with `parent_case_id` set to the archived id (§4.10.3).
    """

    reopen_reason: str = Field(min_length=16, max_length=1024)


class CaseArchiveRequest(ApiSchema):
    """Body for POST /v1/cases/{case_id}/archive. Closed → archived (§4.10.3).

    Requires `admin:case`. Archive bar is `reason` ≥ 32 chars.
    """

    archive_reason: str = Field(min_length=32, max_length=1024)


# ── Case members ─────────────────────────────────────────────────────────


class CaseMemberSummary(ApiSchema):
    """One `case_member` row — active or soft-removed (§4.10.1)."""

    member_id: UUID
    case_id: UUID
    subject_kind: CaseSubjectKind
    subject_id: UUID
    added_by_user_id: UUID
    added_at: datetime
    add_reason: str = Field(max_length=1024)
    active: bool
    removed_at: datetime | None = None
    removed_by_user_id: UUID | None = None
    removal_reason: str | None = Field(default=None, max_length=1024)


class CursorPageCaseMemberSummary(ApiSchema):
    """Cursor-paginated member listing."""

    items: list[CaseMemberSummary] = Field(default_factory=list)
    next_cursor: str | None = None
    estimated_total: int | None = Field(default=None, ge=0)


class CaseMemberAddRequest(ApiSchema):
    """Body for POST /v1/cases/{case_id}/members — single subject."""

    subject_kind: CaseSubjectKind
    subject_id: UUID
    add_reason: str = Field(min_length=16, max_length=1024)


class CaseMemberRemoveRequest(ApiSchema):
    """Body for DELETE /v1/cases/{case_id}/members/{member_id}. Soft-removes."""

    removal_reason: str = Field(min_length=16, max_length=1024)


class CaseMemberSubjectRef(ApiSchema):
    """One subject in a bulk add request."""

    subject_kind: CaseSubjectKind
    subject_id: UUID


class CaseMemberBulkAddRequest(ApiSchema):
    """Body for POST /v1/cases/{case_id}/members/bulk. Atomic, up to 500 subjects."""

    subjects: list[CaseMemberSubjectRef] = Field(min_length=1, max_length=500)
    add_reason: str = Field(min_length=16, max_length=1024)


class CaseMemberBulkRemoveRequest(ApiSchema):
    """Body for POST /v1/cases/{case_id}/members/bulk-remove. Atomic, up to 500 ids."""

    member_ids: list[UUID] = Field(min_length=1, max_length=500)
    removal_reason: str = Field(min_length=16, max_length=1024)


class CaseMemberBulkResult(ApiSchema):
    """200 envelope returned by both bulk member endpoints."""

    case_id: UUID
    affected_member_ids: list[UUID] = Field(default_factory=list)
    audit_event_ids: list[UUID] = Field(default_factory=list)
    effective_tier: SensitivityTier
    prior_effective_tier: SensitivityTier


# ── Case collaborators ───────────────────────────────────────────────────


class CaseCollaboratorSummary(ApiSchema):
    """One `case_collaborator` row (§4.10.1)."""

    collaborator_id: UUID
    case_id: UUID
    user_id: UUID
    role_on_case: CaseRoleOnCase
    granted_by_user_id: UUID
    granted_at: datetime
    active: bool
    revoked_at: datetime | None = None
    revoked_by_user_id: UUID | None = None
    revocation_reason: str | None = Field(default=None, max_length=1024)


class CursorPageCaseCollaboratorSummary(ApiSchema):
    """Cursor-paginated collaborator listing."""

    items: list[CaseCollaboratorSummary] = Field(default_factory=list)
    next_cursor: str | None = None
    estimated_total: int | None = Field(default=None, ge=0)


class CaseCollaboratorAddRequest(ApiSchema):
    """Body for POST /v1/cases/{case_id}/collaborators."""

    user_id: UUID
    role_on_case: CaseRoleOnCase


class CaseCollaboratorRevokeRequest(ApiSchema):
    """Body for DELETE /v1/cases/{case_id}/collaborators/{collaborator_id}.

    ``revocation_reason`` floors at 16 chars to match the storage layer (and
    every other case reason field) — a shorter reason is rejected at validation
    (422) rather than surfacing as a 409 from storage.
    """

    revocation_reason: str = Field(min_length=16, max_length=1024)


__all__ = [
    "CaseArchiveRequest",
    "CaseCloseRequest",
    "CaseCollaboratorAddRequest",
    "CaseCollaboratorRevokeRequest",
    "CaseCollaboratorSummary",
    "CaseCreateRequest",
    "CaseDetail",
    "CaseMemberAddRequest",
    "CaseMemberBulkAddRequest",
    "CaseMemberBulkRemoveRequest",
    "CaseMemberBulkResult",
    "CaseMemberRemoveRequest",
    "CaseMemberSubjectRef",
    "CaseMemberSummary",
    "CaseReopenRequest",
    "CaseSummary",
    "CaseUpdateRequest",
    "CursorPageCaseCollaboratorSummary",
    "CursorPageCaseMemberSummary",
    "CursorPageCaseSummary",
]
