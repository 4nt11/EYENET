# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/cases/{case_id}/members/by-actor — add an actor and (optionally) all their posts.

The reader's "open a case on this author" action. Adds the ACTOR as the tracked member
and, when ``include_posts`` is set, materializes every post we hold by that actor (up to a
generous cap) as MESSAGE members, server-side and batched — so a prolific actor like a
darkforums leaker lands with their whole on-disk post history in one call. Duplicate
subjects (already-active members) are skipped, not errored, so re-running is idempotent-ish.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_audit, get_storage
from eyenet.api.v1.cases._detail import audit_ctx
from eyenet.api.v1.schemas.cases import CaseActorAddRequest, CaseMemberBulkResult
from eyenet.contracts.enums import CaseSubjectKind
from eyenet.models.message import MessageTable
from eyenet.storage.errors import CaseError
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["cases"])

_PAGE = 500
_MAX_POSTS = 2000  # cap the one-shot materialization; deeper history is a later backfill


@router.post(
    "/cases/{case_id}/members/by-actor",
    operation_id="cases_add_actor",
    response_model=CaseMemberBulkResult,
    status_code=200,
)
async def cases_add_actor(
    case_id: UUID,
    body: CaseActorAddRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:cases"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> CaseMemberBulkResult:
    case = await storage.get_case(case_id)
    if case is None:
        raise ResourceNotFound("case")
    prior_tier = case.effective_tier
    ctx = audit_ctx(audit)
    affected: list[UUID] = []

    async def _add(kind: CaseSubjectKind, subject_id: UUID) -> None:
        try:
            row = await storage.add_case_member(
                case_id=case_id,
                subject_kind=kind,
                subject_id=subject_id,
                added_by_user_id=current_user.user_id,
                reason=body.add_reason,
                **ctx,
            )
        except CaseError:
            return  # already a member (or soft-conflict) — skip, don't fail the batch
        affected.append(row.id)

    await _add(CaseSubjectKind.ACTOR, body.actor_id)

    if body.include_posts:
        offset = 0
        while offset < _MAX_POSTS:
            rows = cast(
                "list[MessageTable]",
                await storage.messages_for_actor(body.actor_id, limit=_PAGE, offset=offset),
            )
            if not rows:
                break
            for m in rows:
                await _add(CaseSubjectKind.MESSAGE, m.id)
            if len(rows) < _PAGE:
                break
            offset += _PAGE

    after = await storage.get_case(case_id)
    if after is None:  # pragma: no cover — existence checked above
        raise ResourceNotFound("case")
    return CaseMemberBulkResult(
        case_id=case_id,
        affected_member_ids=affected,
        audit_event_ids=[],
        effective_tier=after.effective_tier,
        prior_effective_tier=prior_tier,
    )
