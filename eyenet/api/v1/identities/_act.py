# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared identity-action write path (M9.G5, API_PLAN §3.4/§10.3).

claim / release / freeze / burn differ only in the resulting state, bus
subject, and whether ``burn_identity`` (state=BURNED, role=QUARANTINE) is used
instead of a plain ``set_identity_state``.

**Documented invariant-#2 exception:** unlike linkage/persona (applied
asynchronously by Graph), identity writes persist ``desired_state`` durably
**in the handler**. There is no live identity supervisor yet, and an operator
under attack must be able to freeze or burn a compromised identity immediately.
The persist happens inside ``operator_write``'s post-audit-gate step, so the
§10.3 order (audit gate → durable state + event log → publish) still holds.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from eyenet.api.deps import ResourceNotFound
from eyenet.api.v1._writes import operator_write
from eyenet.contracts._base import TraceContext
from eyenet.contracts.enums import IdentityState
from eyenet.contracts.identity import IdentityActionEnvelope

if TYPE_CHECKING:
    from eyenet.api.deps import CurrentUser
    from eyenet.api.v1.schemas.identities import IdentityActionRequest
    from eyenet.api.v1.schemas.writes import WriteAccepted
    from eyenet.bus.publisher import BusEnvelopePublisher
    from eyenet.storage.repository import BaseRepository
    from eyenet.telemetry.audit import AuditEmitter


def _resolve_id(raw: str) -> UUID:
    """Path id → UUID. An unparsable id is simply 'not found' (no oracle)."""
    try:
        return UUID(raw)
    except ValueError as exc:
        raise ResourceNotFound("identity") from exc


async def act_on_identity(
    *,
    identity_id_raw: str,
    body: IdentityActionRequest,
    action: str,
    subject: str,
    new_state: IdentityState,
    burn: bool,
    storage: BaseRepository,
    audit: AuditEmitter,
    publisher: BusEnvelopePublisher,
    current_user: CurrentUser,
) -> WriteAccepted:
    identity_id = _resolve_id(identity_id_raw)
    if await storage.get_identity(identity_id) is None:
        raise ResourceNotFound("identity")
    decided_at = datetime.now(tz=UTC)

    async def _persist(event_id: UUID, traceparent: str) -> None:
        if burn:
            await storage.burn_identity(identity_id=identity_id)
        else:
            await storage.set_identity_state(identity_id=identity_id, state=new_state)
        await storage.append_identity_event(
            identity_id=identity_id,
            event_subject=subject,
            event_id=event_id,
            traceparent=traceparent,
            actor=str(current_user.user_id),
        )

    async def _publish(event_id: UUID, traceparent: str) -> None:
        await publisher.publish(
            subject,
            IdentityActionEnvelope(
                identity_id=identity_id,
                new_state=new_state,
                decided_by=current_user.username,
                decided_at=decided_at,
                reason=body.reason,
                trace_context=TraceContext(traceparent=traceparent),
            ),
            event_id=event_id,
        )

    return await operator_write(
        audit=audit,
        subject_kind="identity",
        subject_id=identity_id,
        system_user_id=current_user.user_id,
        audit_payload={
            "action": action,
            "reason": body.reason,
            "note": body.note,
            "new_state": new_state.value,
        },
        subject=subject,
        poll=f"/v1/identities/{identity_id}",
        persist_event=_persist,
        publish_event=_publish,
    )


__all__ = ["act_on_identity"]
