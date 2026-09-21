"""POST /v1/panic — global kill-switch: freeze the fleet, page the operator.

Grant-only ``write:panic`` (never in a role baseline). Publishes
``eyenet.control.panic`` on the control channel every service watches; the UI
raises a banner off the control stream. No per-entity state mutation and no
event-log row — the audit chain is the durable record for a control action.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_publisher
from eyenet.api.v1._writes import operator_write
from eyenet.api.v1.schemas.identities import PanicRequest
from eyenet.api.v1.schemas.writes import WriteAccepted
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts._base import TraceContext
from eyenet.contracts.control import SUBJECT_PANIC, PanicEnvelope
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["control"])


@router.post(
    "/panic",
    operation_id="control_panic",
    response_model=WriteAccepted,
    status_code=202,
)
async def control_panic(
    body: PanicRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:panic"))],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    publisher: Annotated[BusEnvelopePublisher, Depends(get_publisher)],
    idempotency_key: Annotated[  # noqa: ARG001 — read by IdempotencyMiddleware; declared for the OpenAPI surface
        str | None, Header(alias="Idempotency-Key", max_length=128)
    ] = None,
) -> WriteAccepted:
    declared_at = datetime.now(UTC)

    async def _no_domain_row(event_id: UUID, traceparent: str) -> None:  # noqa: ARG001 — panic has no per-entity state; the audit chain is the record
        return

    async def _publish(event_id: UUID, traceparent: str) -> None:  # noqa: ARG001 — envelope carries the trace
        await publisher.publish(
            SUBJECT_PANIC,
            PanicEnvelope(
                declared_by=current_user.username,
                declared_at=declared_at,
                reason=body.reason,
                trace_context=TraceContext(traceparent=traceparent),
            ),
        )

    return await operator_write(
        audit=audit,
        subject_kind="control",
        subject_id=None,
        system_user_id=current_user.user_id,
        audit_payload={"action": "panic", "reason": body.reason},
        subject=SUBJECT_PANIC,
        poll="/v1/healthz",
        persist_event=_no_domain_row,
        publish_event=_publish,
    )
