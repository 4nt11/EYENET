# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared linkage-decision write path (M9.G3, API_PLAN §3.4/§10.3).

The confirm/reject/suspect handlers differ only in decision label, bus subject,
and envelope type — everything else (404 guard, audit gate, event-log append,
publish, 202) is this one function. The API never mutates the linkage state
itself: it publishes the decision and the Graph service applies the transition
(invariant #2), so ``WriteAccepted.applied`` is always False + a poll URL.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from eyenet.api.deps import ResourceNotFound
from eyenet.api.v1._writes import operator_write
from eyenet.contracts._base import TraceContext

if TYPE_CHECKING:
    from eyenet.api.deps import CurrentUser
    from eyenet.api.v1.schemas.linkages import LinkageDecisionRequest
    from eyenet.api.v1.schemas.writes import WriteAccepted
    from eyenet.bus.publisher import BusEnvelopePublisher
    from eyenet.contracts.attribution import _LinkageDecisionBase
    from eyenet.storage.repository import BaseRepository
    from eyenet.telemetry.audit import AuditEmitter


async def decide_linkage(
    *,
    linkage_id: UUID,
    body: LinkageDecisionRequest,
    decision: str,
    subject: str,
    envelope_cls: type[_LinkageDecisionBase],
    storage: BaseRepository,
    audit: AuditEmitter,
    publisher: BusEnvelopePublisher,
    current_user: CurrentUser,
) -> WriteAccepted:
    linkage = await storage.get_linkage(linkage_id)
    if linkage is None:
        raise ResourceNotFound("linkage")
    decided_at = datetime.now(tz=UTC)

    async def _persist(event_id: UUID, traceparent: str) -> None:
        await storage.append_linkage_event(
            linkage_id=linkage_id,
            event_subject=subject,
            event_id=event_id,
            traceparent=traceparent,
            actor=str(current_user.user_id),
        )

    async def _publish(event_id: UUID, traceparent: str) -> None:  # noqa: ARG001 — event_id rides in the event log; the envelope carries the trace
        envelope = envelope_cls.from_pair(
            linkage.actor_a_id,
            linkage.actor_b_id,
            linkage_id=linkage_id,
            decided_by=current_user.username,
            decided_at=decided_at,
            notes=body.note,
            trace_context=TraceContext(traceparent=traceparent),
        )
        await publisher.publish(subject, envelope)

    return await operator_write(
        audit=audit,
        subject_kind="linkage",
        subject_id=linkage_id,
        system_user_id=current_user.user_id,
        audit_payload={
            "decision": decision,
            "reason": body.reason,
            "note": body.note,
            "actor_a_id": str(linkage.actor_a_id),
            "actor_b_id": str(linkage.actor_b_id),
        },
        subject=subject,
        poll=f"/v1/linkages/{linkage_id}",
        persist_event=_persist,
        publish_event=_publish,
    )


__all__ = ["decide_linkage"]
