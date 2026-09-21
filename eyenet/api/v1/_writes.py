# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared operator-write orchestration (API_PLAN §3.4 / §10.3, M9 Group G).

Every §3.4 operator decision (linkage confirm/reject/suspect, identity
claim/release/freeze/burn/freeze_all, persona merge/split, panic) runs the same
durable sequence, centralized here so each handler stays a thin adapter:

1. **Durable audit ``operator_action``** — the gate. If the audit log is
   unavailable the write is refused with 503; nothing else happens.
2. **Durable event-log append** — the per-transition replay row (§11.5), so the
   Group H SSE stream can replay with the right ``traceparent``.
3. **Async bus publish** — the domain event the applier (Graph) / observers act
   on. A bus failure does NOT roll back storage: the decision is already
   durable (audit + event log) and a retry walker catches up; we log and return
   the 202 anyway (§10.3).

Idempotency replay/finalize is handled one layer out, in the ASGI
``IdempotencyMiddleware`` — this helper is only ever reached on the first
(winning) request for a key.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog
from sqlalchemy.exc import SQLAlchemyError
from uuid_extensions import uuid7

from eyenet.api.deps import ServiceUnavailableError
from eyenet.api.v1.schemas.writes import WriteAccepted
from eyenet.telemetry.propagation import ZERO_TRACEPARENT, current_traceparent

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from eyenet.telemetry.audit import AuditEmitter

_log = structlog.get_logger()

AUDIT_OPERATOR_ACTION = "eyenet.audit.operator_action"


async def operator_write(
    *,
    audit: AuditEmitter,
    subject_kind: str,
    subject_id: UUID | None,
    system_user_id: UUID | None,
    audit_payload: dict[str, Any],
    subject: str,
    poll: str,
    persist_event: Callable[[UUID, str], Awaitable[Any]],
    publish_event: Callable[[UUID, str], Awaitable[Any]],
) -> WriteAccepted:
    """Run the §10.3 durable sequence and return the 202 ``WriteAccepted``.

    ``persist_event`` and ``publish_event`` are each called with
    ``(event_id, traceparent)``: the caller closes over the domain-specific
    storage append (``append_*_event``) and the typed envelope publish.
    """
    event_id = UUID(str(uuid7()))
    traceparent = current_traceparent() or ZERO_TRACEPARENT

    # 1. Durable audit operator_action — the gate.
    try:
        await audit.emit(
            event=AUDIT_OPERATOR_ACTION,
            subject_kind=subject_kind,
            subject_id=subject_id,
            system_user_id=system_user_id,
            payload={**audit_payload, "event_id": str(event_id), "subject": subject},
        )
    except (SQLAlchemyError, OSError) as exc:
        raise ServiceUnavailableError("audit log unavailable; operator write refused") from exc

    # 2. Durable event-log append (replay source, §11.5).
    await persist_event(event_id, traceparent)

    # 3. Async bus publish. Decision is already durable; a bus failure must not
    #    roll back storage — log and continue (§10.3 retry-walker semantics).
    try:
        await publish_event(event_id, traceparent)
    except (OSError, ConnectionError, TimeoutError) as exc:
        _log.warning(
            "operator_write.bus_publish_failed",
            subject=subject,
            event_id=str(event_id),
            error=str(exc),
        )

    return WriteAccepted(subject=subject, event_id=event_id, applied=False, poll=poll)


__all__ = ["AUDIT_OPERATOR_ACTION", "operator_write"]
