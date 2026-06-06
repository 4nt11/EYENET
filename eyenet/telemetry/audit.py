"""`AuditEmitter` — emits `eyenet.audit.{service}` envelopes AND persists.

Single call writes both. The bus envelope and the persisted row share the
same `audit_id`. Hash chain is computed at the storage layer's write time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from opentelemetry import trace
from uuid_extensions import uuid7

from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts._base import TraceContext
from eyenet.contracts.audit import AuditEvent, subject_for
from eyenet.storage.repository import BaseRepository

from .propagation import current_traceparent

_tracer = trace.get_tracer("eyenet.telemetry.audit")


class AuditEmitter:
    """Combines the bus emit + the chained-row write."""

    def __init__(
        self,
        publisher: BusEnvelopePublisher,
        store: BaseRepository,
        *,
        service: str,
        instance_id: str,
    ) -> None:
        self._publisher = publisher
        self._store = store
        self._service = service
        self._instance_id = instance_id

    @property
    def service(self) -> str:
        """The configured service name (for callers passing it to self-auditing
        storage methods, e.g. the Case mixin)."""
        return self._service

    @property
    def instance_id(self) -> str:
        """The configured instance id (see :attr:`service`)."""
        return self._instance_id

    async def emit(
        self,
        *,
        event: str,
        subject_kind: str,
        subject_id: UUID | None = None,
        evidence_ref: str | None = None,
        system_user_id: UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        audit_id = UUID(str(uuid7()))
        at = datetime.now(tz=UTC)
        with _tracer.start_as_current_span(
            "audit.emit",
            attributes={
                "audit.event": event,
                "audit.subject_kind": subject_kind,
                "audit.subject_id": str(subject_id) if subject_id else "",
                "audit.id": str(audit_id),
                "audit.service": self._service,
            },
        ):
            traceparent = current_traceparent() or _zero_traceparent()
            tc = TraceContext(traceparent=traceparent)
            envelope = AuditEvent(
                audit_id=audit_id,
                event=event,
                service=self._service,
                instance_id=self._instance_id,
                system_user_id=system_user_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                evidence_ref=evidence_ref,
                payload=payload or {},
                at=at,
                trace_context=tc,
            )
            await self._publisher.publish(subject_for(self._service), envelope)
            await self._store.append_audit(
                {
                    "id": audit_id,
                    "event": event,
                    "service": self._service,
                    "instance_id": self._instance_id,
                    "system_user_id": system_user_id,
                    "subject_kind": subject_kind,
                    "subject_id": subject_id,
                    "evidence_ref": evidence_ref,
                    "trace_id": _trace_id_from_traceparent(traceparent),
                    "span_id": _span_id_from_traceparent(traceparent),
                    "payload": payload or {},
                    "at": at,
                }
            )


def _zero_traceparent() -> str:
    # Valid 55-char W3C traceparent with all-zero ids — used when no active span.
    return "00-" + "0" * 32 + "-" + "0" * 16 + "-00"


_TP_FIELDS = 4  # traceparent: version-traceid-spanid-flags


def _trace_id_from_traceparent(tp: str) -> str | None:
    parts = tp.split("-")
    return parts[1] if len(parts) == _TP_FIELDS else None


def _span_id_from_traceparent(tp: str) -> str | None:
    parts = tp.split("-")
    return parts[2] if len(parts) == _TP_FIELDS else None


__all__ = ["AuditEmitter"]
