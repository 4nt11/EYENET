"""POST /v1/identities/freeze_all — fleet-wide soft freeze of every identity."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_publisher, get_storage
from eyenet.api.v1._writes import operator_write
from eyenet.api.v1.schemas.identities import IdentityActionRequest
from eyenet.api.v1.schemas.writes import WriteAccepted
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts._base import TraceContext
from eyenet.contracts.identity import SUBJECT_IDENTITY_FREEZE_ALL, IdentityFreezeAllEnvelope
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["identities"])


@router.post(
    "/identities/freeze_all",
    operation_id="identities_freeze_all",
    response_model=WriteAccepted,
    status_code=202,
)
async def identities_freeze_all(
    body: IdentityActionRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:identity"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    publisher: Annotated[BusEnvelopePublisher, Depends(get_publisher)],
    idempotency_key: Annotated[  # noqa: ARG001 — read by IdempotencyMiddleware; declared for the OpenAPI surface
        str | None, Header(alias="Idempotency-Key", max_length=128)
    ] = None,
) -> WriteAccepted:
    # Fleet-wide control action: no per-identity event-log rows (the single
    # audit row + the freeze_all envelope's id-list are the record). The bulk
    # mutation runs in the post-audit-gate step; the frozen ids flow to the
    # envelope via this holder.
    frozen: list[UUID] = []

    async def _persist(event_id: UUID, traceparent: str) -> None:  # noqa: ARG001 — no per-id event log for a fleet action
        frozen.extend(await storage.freeze_all_identities())

    async def _publish(event_id: UUID, traceparent: str) -> None:  # noqa: ARG001 — envelope carries the trace
        await publisher.publish(
            SUBJECT_IDENTITY_FREEZE_ALL,
            IdentityFreezeAllEnvelope(
                frozen_identity_ids=frozen,
                decided_by=current_user.username,
                decided_at=datetime.now(UTC),
                reason=body.reason,
                trace_context=TraceContext(traceparent=traceparent),
            ),
        )

    return await operator_write(
        audit=audit,
        subject_kind="identity",
        subject_id=None,
        system_user_id=current_user.user_id,
        audit_payload={"action": "freeze_all", "reason": body.reason, "note": body.note},
        subject=SUBJECT_IDENTITY_FREEZE_ALL,
        poll="/v1/identities",
        persist_event=_persist,
        publish_event=_publish,
    )
