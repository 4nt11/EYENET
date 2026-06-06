# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared projections + access helpers for the Case handlers (API_PLAN §4.10).

The Case storage methods self-audit (they write the hash-chained row directly),
so handlers pass them the audit attribution context via :func:`audit_ctx` and
do **not** double-emit. The ``actor`` of each case audit row is the user-id
argument the storage method already takes (``opened_by_user_id`` /
``editor_user_id`` / …).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from eyenet.api.deps import ResourceNotFound, ScopeForbidden
from eyenet.api.v1.schemas.cases import (
    CaseCollaboratorSummary,
    CaseDetail,
    CaseMemberSummary,
    CaseSummary,
)
from eyenet.contracts.enums import CaseRoleOnCase
from eyenet.telemetry.propagation import current_traceparent

if TYPE_CHECKING:
    from eyenet.api.deps import CurrentUser
    from eyenet.contracts.case import CaseCollaboratorRow, CaseMemberRow, CaseRow
    from eyenet.storage.repository import BaseRepository
    from eyenet.telemetry.audit import AuditEmitter

_ADMIN_CASE = "admin:case"
_TP_FIELDS = 4  # W3C traceparent: version-traceid-spanid-flags


def audit_ctx(audit: AuditEmitter) -> dict[str, Any]:
    """``service``/``instance_id``/``trace_id``/``span_id`` kwargs for the
    self-auditing Case storage methods, spread into the call."""
    tp = current_traceparent()
    parts = tp.split("-") if tp else []
    trace_id = parts[1] if len(parts) == _TP_FIELDS else None
    span_id = parts[2] if len(parts) == _TP_FIELDS else None
    return {
        "service": audit.service,
        "instance_id": audit.instance_id,
        "trace_id": trace_id,
        "span_id": span_id,
    }


def to_case_summary(row: CaseRow) -> CaseSummary:
    """Index projection (member/collaborator counts left None — see §4.10)."""
    return CaseSummary(
        case_id=row.id,
        title=row.title,
        status=row.status,
        effective_tier=row.effective_tier,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
    )


async def build_case_detail(storage: BaseRepository, case_id: UUID) -> CaseDetail | None:
    """Full detail projection with live member/collaborator counts, or None."""
    row = await storage.get_case(case_id)
    if row is None:
        return None
    members = await storage.list_case_members(case_id)
    collaborators = await storage.list_case_collaborators(case_id)
    return CaseDetail(
        case_id=row.id,
        title=row.title,
        status=row.status,
        effective_tier=row.effective_tier,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        member_count=len(members),
        collaborator_count=len(collaborators),
        description=row.description,
        closed_at=row.closed_at,
        closed_by_user_id=row.closed_by_user_id,
        close_reason=row.close_reason,
        archived_at=row.archived_at,
        archived_by_user_id=row.archived_by_user_id,
        archive_reason=row.archive_reason,
        parent_case_id=row.parent_case_id,
    )


def to_member_summary(row: CaseMemberRow) -> CaseMemberSummary:
    return CaseMemberSummary(
        member_id=row.id,
        case_id=row.case_id,
        subject_kind=row.subject_kind,
        subject_id=row.subject_id,
        added_by_user_id=row.added_by_user_id,
        added_at=row.added_at,
        add_reason=row.add_reason,
        active=row.removed_at is None,
        removed_at=row.removed_at,
        removed_by_user_id=row.removed_by_user_id,
        removal_reason=row.removal_reason,
    )


def to_collaborator_summary(row: CaseCollaboratorRow) -> CaseCollaboratorSummary:
    return CaseCollaboratorSummary(
        collaborator_id=row.id,
        case_id=row.case_id,
        user_id=row.user_id,
        role_on_case=row.role_on_case,
        granted_by_user_id=row.granted_by_user_id,
        granted_at=row.granted_at,
        active=row.revoked_at is None,
        revoked_at=row.revoked_at,
        revoked_by_user_id=row.revoked_by_user_id,
        revocation_reason=row.revocation_reason,
    )


def has_admin_case(user: CurrentUser) -> bool:
    return _ADMIN_CASE in user.effective_scopes


async def is_case_collaborator(storage: BaseRepository, case_id: UUID, user_id: UUID) -> bool:
    """True iff ``user_id`` is any active collaborator on the case."""
    return any(c.user_id == user_id for c in await storage.list_case_collaborators(case_id))


async def require_case_visible(
    storage: BaseRepository, case_id: UUID, user: CurrentUser
) -> CaseRow:
    """§4.10.4 read-visibility: the case must exist AND the caller must hold
    ``admin:case`` or be an active collaborator. Returns the row.

    Raises :class:`ResourceNotFound` both when the case is absent and when the
    caller may not see it — a non-collaborator must not be able to distinguish
    the two (no case-existence oracle)."""
    row = await storage.get_case(case_id)
    if row is None:
        raise ResourceNotFound("case")
    if has_admin_case(user) or await is_case_collaborator(storage, case_id, user.user_id):
        return row
    raise ResourceNotFound("case")


async def is_case_owner(storage: BaseRepository, case_id: UUID, user_id: UUID) -> bool:
    """True iff ``user_id`` is an active OWNER collaborator on the case."""
    for collab in await storage.list_case_collaborators(case_id):
        if collab.user_id == user_id and collab.role_on_case is CaseRoleOnCase.OWNER:
            return True
    return False


async def require_owner_or_admin_case(
    storage: BaseRepository, case_id: UUID, user: CurrentUser
) -> None:
    """§4.10.3 gate: the caller must own the case OR hold ``admin:case``.

    Raises :class:`ScopeForbidden` otherwise (the case's existence is already
    confirmed by the caller, so 403 — not 404 — is the right signal here)."""
    if has_admin_case(user):
        return
    if await is_case_owner(storage, case_id, user.user_id):
        return
    raise ScopeForbidden(_ADMIN_CASE)
