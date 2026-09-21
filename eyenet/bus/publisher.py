"""`BusEnvelopePublisher` — wraps `Bus.publish` to enforce trace propagation.

PLAN §8.2: every envelope on the bus carries a `trace_context`. Hand
discipline drifts; this wrapper refuses to publish without one and injects
the W3C `traceparent` / `tracestate` headers automatically.
"""

from __future__ import annotations

from uuid import UUID

from behave_text.spec import Observation, event_topic_for
from opentelemetry import trace

from eyenet.contracts._base import BusEnvelope
from eyenet.contracts.bus import Bus

_tracer = trace.get_tracer("eyenet.bus.publisher")

# Allowed subject patterns documented in PLAN §3. Acceptance is permissive
# enough to allow rendered subjects ("raw.message.telegram.abcd1234") AND
# the bus subject patterns ("eyenet.audit.>", "actor.observation.text.>").
_ALLOWED_PREFIXES: tuple[str, ...] = (
    "raw.message.",
    "actor.observation.text.",
    "identity.label.applied",
    "identity.engagement.authorized",
    "attribution.profile.candidate",
    "attribution.profile.current",
    "attribution.linkage.proposed",
    "attribution.linkage.suspected",
    "attribution.linkage.confirmed",
    "attribution.linkage.rejected",
    "attribution.persona.updated",
    "attribution.persona.merge",
    "attribution.persona.split",
    "classify.document.uploaded",
    "classify.attachment.stored",
    "eyenet.audit.",
    "eyenet.control.",
    "eyenet.identity.",
)


def _is_known_subject(subject: str) -> bool:
    return any(subject == p or subject.startswith(p) for p in _ALLOWED_PREFIXES)


class BusEnvelopePublisher:
    """Type-safe envelope publisher. Service code uses this, not raw `Bus.publish`."""

    def __init__(self, bus: Bus) -> None:
        self._bus = bus

    @property
    def bus(self) -> Bus:
        """The wrapped bus — the SSE delivery path (Group H) subscribes on it."""
        return self._bus

    async def publish(
        self, subject: str, envelope: BusEnvelope, *, event_id: UUID | None = None
    ) -> None:
        if not _is_known_subject(subject):
            raise ValueError(
                f"refusing to publish on unknown subject {subject!r}; "
                "register it in PLAN §3 / publisher._ALLOWED_PREFIXES"
            )
        if not envelope.trace_context.traceparent:
            raise ValueError("BusEnvelope.trace_context.traceparent must be set")
        headers: dict[str, str] = {
            "traceparent": envelope.trace_context.traceparent,
            "schema-version": envelope.schema_version,
        }
        if envelope.trace_context.tracestate:
            headers["tracestate"] = envelope.trace_context.tracestate
        # The durable event_id (event-log PK, §11.5) rides as a header so the
        # Group H SSE stream can dedup a live event against the same event
        # replayed from storage (exact-once across the replay→live boundary).
        if event_id is not None:
            headers["eyenet-event-id"] = str(event_id)
        payload = envelope.model_dump_json().encode("utf-8")
        with _tracer.start_as_current_span(
            "bus.publish",
            attributes={
                "messaging.system": "eyenet",
                "messaging.destination": subject,
                "messaging.operation": "publish",
                "messaging.message.payload_size_bytes": len(payload),
                "schema.version": envelope.schema_version,
            },
        ):
            await self._bus.publish(subject, payload, headers=headers)

    async def publish_observation(self, obs: Observation) -> None:
        """Publish a BEHAVE-TEXT Observation envelope.

        `Observation` is NOT a `BusEnvelope` (it's owned by BEHAVE-TEXT and does
        not embed TraceContext inline — per _base.py comment). Trace context is
        propagated via NATS message headers as per PLAN §8.2.
        """
        # Local import: top-level would create a circular dep with telemetry.
        from eyenet.telemetry.propagation import current_traceparent  # noqa: PLC0415

        subject = event_topic_for(obs.primitive)
        if not _is_known_subject(subject):
            raise ValueError(f"refusing to publish observation on unknown subject {subject!r}")
        traceparent = current_traceparent()
        headers: dict[str, str] = {"schema-version": str(obs.v)}
        if traceparent:
            headers["traceparent"] = traceparent
        payload = obs.model_dump_json().encode("utf-8")
        with _tracer.start_as_current_span(
            "bus.publish",
            attributes={
                "messaging.system": "eyenet",
                "messaging.destination": subject,
                "messaging.operation": "publish",
                "messaging.message.payload_size_bytes": len(payload),
                "schema.version": str(obs.v),
            },
        ):
            await self._bus.publish(subject, payload, headers=headers)


__all__ = ["BusEnvelopePublisher"]
