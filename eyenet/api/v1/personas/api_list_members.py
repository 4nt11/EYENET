# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/personas/{persona_id}/members — paginated members (M9.F1)."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from eyenet.api.deps import (
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    get_audit,
    get_publisher,
    get_storage,
)
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.personas._emit import emit_persona_updated
from eyenet.api.v1.schemas.personas import (
    CursorPagePersonaMember,
    PersonaAddMemberRequest,
    PersonaMember,
)
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts.attribution import PersonaChangeKind, PersonaRow
from eyenet.models.persona import PersonaMembershipTable
from eyenet.storage.repository import BaseRepository
from eyenet.storage.sqlmodel_repo.personas import PersonaIntegrityError
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["personas"])


@router.get(
    "/personas/{persona_id}/members",
    operation_id="personas_members",
    response_model=CursorPagePersonaMember,
    status_code=200,
)
async def personas_members(
    persona_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:personas"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
) -> CursorPagePersonaMember:
    if await storage.get_persona(persona_id) is None:
        raise ResourceNotFound("persona")
    rows = cast(
        "list[PersonaMembershipTable]",
        await storage.list_persona_memberships(
            persona_id, limit=page.fetch_limit, offset=page.offset
        ),
    )
    estimated_total = (
        await storage.count_persona_memberships(persona_id) if page.include_total else None
    )
    return CursorPagePersonaMember(
        items=[PersonaMember.from_domain(r) for r in rows[: page.limit]],
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )


@router.post(
    "/personas/{persona_id}/members",
    operation_id="personas_add_member",
    status_code=204,
)
async def personas_add_member(
    persona_id: UUID,
    body: PersonaAddMemberRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:persona_decision"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    publisher: Annotated[BusEnvelopePublisher, Depends(get_publisher)],
) -> None:
    """Attach one actor to this persona (operator 'add to persona' from the graph). A direct
    synchronous write so the persona browse surface reflects it at once. 409 if the actor
    already belongs to a different persona."""
    try:
        persona = cast("PersonaRow", await storage.add_actor_to_persona(persona_id, body.actor_id))
    except PersonaIntegrityError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    await audit.emit(
        event="eyenet.audit.persona.member_added",
        subject_kind="persona",
        subject_id=persona_id,
        system_user_id=current_user.user_id,
        payload={"actor_id": str(body.actor_id)},
    )
    await emit_persona_updated(
        publisher,
        persona_id=persona_id,
        member_actor_ids=persona.member_actor_ids,
        change_kind=PersonaChangeKind.MEMBERS_ADDED,
    )


@router.delete(
    "/personas/{persona_id}/members/{actor_id}",
    operation_id="personas_remove_member",
    status_code=204,
)
async def personas_remove_member(
    persona_id: UUID,
    actor_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:persona_decision"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    publisher: Annotated[BusEnvelopePublisher, Depends(get_publisher)],
) -> None:
    """Unlink one actor from this persona (operator 'remove from persona' from the graph).
    The persona SURVIVES even if this empties it (it is a deliberate labelled entity;
    deleting it is a separate explicit action). 404 if the actor is not a member of THIS
    persona."""
    remaining = cast(
        "PersonaRow | None", await storage.remove_actor_from_persona(persona_id, actor_id)
    )
    if remaining is None:
        raise ResourceNotFound("persona member")
    await audit.emit(
        event="eyenet.audit.persona.member_removed",
        subject_kind="persona",
        subject_id=persona_id,
        system_user_id=current_user.user_id,
        payload={"actor_id": str(actor_id)},
    )
    await emit_persona_updated(
        publisher,
        persona_id=persona_id,
        member_actor_ids=remaining.member_actor_ids,
        change_kind=PersonaChangeKind.MEMBERS_REMOVED,
    )
