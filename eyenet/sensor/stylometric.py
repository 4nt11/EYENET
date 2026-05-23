"""`StylometricSensor` — runs the four M2 stylometric/lexical primitives.

Subscribes to `raw.message.>` (queue group `sensor`), resolves actor_key →
actor_id, derefs evidence_ref from MessageStore, runs each primitive over the
per-actor corpus window, persists ObservationRows, publishes to the bus.

PLAN §8.3 failure isolation: a broken primitive marks its span errored and
skips, but NEVER aborts its siblings.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

import structlog
from behave_text.spec import PRIMITIVE_REGISTRY, ValueTypeSpec
from opentelemetry import trace
from sqlmodel import Session

from eyenet.contracts.enums import ValueKind
from eyenet.contracts.observation import ObservationEnvelope, ObservationRow
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.contracts.sensor import SensorBase
from eyenet.sensor.primitives import PRIMITIVES, PrimitiveSpec
from eyenet.service import ServiceBase
from eyenet.storage.actors import resolve_actor_id
from eyenet.storage.engines import StoreName

_tracer = trace.get_tracer("eyenet.sensor.stylometric")
_log = structlog.get_logger()

_SENSOR_INSTANCE = "stylometric_default"
_RETRY_DELAY = 0.05  # seconds to wait on actor-not-yet-ingested race


class StylometricSensor(ServiceBase, SensorBase):
    """Stylometric sensor running the 4 M2 primitives."""

    @property
    def name(self) -> str:
        return "sensor"

    @property
    def instance_id(self) -> str:
        return _SENSOR_INSTANCE

    def primitives(self) -> Iterable[tuple[str, ValueTypeSpec]]:
        return [
            (p.name, PRIMITIVE_REGISTRY[p.name]) for p in PRIMITIVES if p.name in PRIMITIVE_REGISTRY
        ]

    async def on_subscribe(self) -> None:
        async def _handler(_subject: str, payload: bytes, _headers: dict[str, str]) -> None:
            try:
                env = RawMessageEnvelope.model_validate_json(payload)
            except Exception as exc:
                _log.error("sensor.envelope_parse_error", error=str(exc))
                return
            # Fire-and-forget: don't block the bus fanout waiting for full primitive compute.
            asyncio.create_task(self._process(env))  # noqa: RUF006

        await self._bus.subscribe("raw.message.>", _handler, queue_group="sensor")

    async def on_raw_message(self, _envelope: RawMessageEnvelope) -> Iterable[ObservationEnvelope]:
        # SensorBase contract; StylometricSensor uses the internal _process path.
        return []

    async def _process(self, env: RawMessageEnvelope) -> None:
        messages_engine = self._storage._engines[StoreName.MESSAGES]

        with Session(messages_engine) as session:
            actor_id = resolve_actor_id(session, env.actor_key)

        if actor_id is None:
            # Race: collector may not have committed the actor row yet.
            await asyncio.sleep(_RETRY_DELAY)
            with Session(messages_engine) as session:
                actor_id = resolve_actor_id(session, env.actor_key)
            if actor_id is None:
                _log.warning(
                    "sensor.actor_not_found",
                    actor_key=env.actor_key,
                    evidence_ref=env.evidence_ref,
                )
                return

        body_bytes = await self._storage.messages.get_by_evidence_ref(env.evidence_ref)
        if body_bytes is None:
            _log.warning("sensor.body_not_found", evidence_ref=env.evidence_ref)
            return

        await self.audit.emit(
            event="evidence_access",
            subject_kind="evidence",
            payload={
                "evidence_ref": env.evidence_ref,
                "actor_id": str(actor_id),
                "reason": "stylometric_sensor_primitive_compute",
            },
        )

        with _tracer.start_as_current_span(
            "sensor.dispatch",
            attributes={
                "service.name": self.name,
                "service.instance_id": self.instance_id,
                "actor.id": str(actor_id),
                "message.evidence_ref": env.evidence_ref,
                "sensor.primitive_count": len(PRIMITIVES),
            },
        ):
            await self._run_primitives(actor_id, env, body_bytes.decode("utf-8"))

    async def _run_primitives(self, actor_id: UUID, env: RawMessageEnvelope, _body: str) -> None:
        cursor_store = self._storage.cursors
        obs_store = self._storage.observations
        messages_engine = self._storage._engines[StoreName.MESSAGES]

        succeeded = failed = 0

        for spec in PRIMITIVES:
            span_name = f"sensor.primitive.{spec.name.replace('.', '.')}"
            with _tracer.start_as_current_span(
                span_name,
                attributes={
                    "primitive.name": spec.name,
                    "primitive.version": spec.version,
                    "primitive.namespace": spec.name.split(".")[0],
                },
            ) as span:
                try:
                    t0 = time.monotonic()
                    obs = await self._compute_primitive(spec, actor_id, env, messages_engine)
                    duration_ms = (time.monotonic() - t0) * 1000
                    span.set_attribute("primitive.duration_ms", duration_ms)

                    if obs is None:
                        span.set_attribute("primitive.outcome", "skipped")
                        span.set_attribute("primitive.skip_reason", "corpus_too_short")
                        _log.debug(
                            "primitive.skipped",
                            primitive=spec.name,
                            actor_id=str(actor_id),
                        )
                    else:
                        span.set_attribute("primitive.outcome", "ok")
                        span.set_attribute("primitive.value", str(obs.value)[:120])

                        # Publish observation envelope
                        await self.publisher.publish_observation(obs)

                        # Persist observation row
                        row = _observation_to_row(obs, actor_id, self.instance_id, spec.version)
                        await obs_store.put(row)

                        # Advance cursor to the current message
                        _advance_cursor(
                            cursor_store,
                            actor_id,
                            spec.name,
                            env,
                            self._storage.messages,
                        )

                        succeeded += 1
                except Exception as exc:
                    failed += 1
                    span.set_attribute("primitive.outcome", "error")
                    span.record_exception(exc)
                    _log.error(
                        "primitive.error",
                        primitive=spec.name,
                        actor_id=str(actor_id),
                        error=str(exc),
                    )

        _log.info(
            "sensor.dispatch.complete",
            actor_id=str(actor_id),
            evidence_ref=env.evidence_ref,
            succeeded=succeeded,
            failed=failed,
        )

    async def _compute_primitive(
        self,
        spec: PrimitiveSpec,
        actor_id: UUID,
        _env: RawMessageEnvelope,
        _messages_engine: object,
    ) -> ObservationEnvelope | None:
        cursor_store = self._storage.cursors
        since_ts, since_msg_id = cursor_store.get(actor_id, spec.name)

        if spec.requires_reply_corpus and spec.compute_with_reply is not None:
            corpus_reply = await self._storage.corpus.iter_since_with_reply(
                actor_id, since_ts, since_msg_id
            )
            if not corpus_reply:
                return None
            return await spec.compute_with_reply(corpus_with_reply=corpus_reply)

        corpus = await self._storage.corpus.iter_since(actor_id, since_ts, since_msg_id)
        if not corpus:
            return None

        # Batch-fetch bodies (all evidence_refs in the window)
        bodies: dict[str, str] = {}
        for _ts, _mid, ref in corpus:
            b = await self._storage.messages.get_by_evidence_ref(ref)
            if b is not None:
                bodies[ref] = b.decode("utf-8")

        return spec.compute(corpus=corpus, bodies=bodies)


def _observation_to_row(
    obs: ObservationEnvelope,
    actor_id: UUID,
    sensor_instance: str,
    primitive_version: str = "0",
) -> ObservationRow:
    """Map a BEHAVE-TEXT Observation to an EYENET ObservationRow."""

    parts = obs.primitive.split(".")
    namespace = parts[0] if parts else obs.primitive

    value = obs.value
    value_hash: str | None = None
    value_numeric: float | None = None
    value_enum: str | None = None
    value_array: list[str] | None = None
    value_array_numeric: list[float] | None = None

    if isinstance(value, str):
        value_hash = value
        vkind = ValueKind.HASH
    elif isinstance(value, float | int) and not isinstance(value, bool):
        value_numeric = float(value)
        vkind = ValueKind.NUMERIC
    elif isinstance(value, list):
        if value and isinstance(value[0], str):
            value_array = value
            vkind = ValueKind.ARRAY_STR
        else:
            value_array_numeric = [float(v) for v in value]
            vkind = ValueKind.ARRAY_NUMERIC
    else:
        value_enum = str(value)
        vkind = ValueKind.ENUM_STR

    window_start: datetime | None = None
    window_end: datetime | None = None
    if obs.window:
        window_start = datetime.fromtimestamp(obs.window.start_ts, tz=UTC)
        window_end = datetime.fromtimestamp(obs.window.end_ts, tz=UTC)

    return ObservationRow(
        actor_id=actor_id,
        evidence_ref=obs.evidence_ref,
        primitive_namespace=namespace,
        primitive_name=obs.primitive,
        primitive_version=primitive_version,
        value_kind=vkind,
        value_hash=value_hash,
        value_numeric=value_numeric,
        value_enum=value_enum,
        value_array=value_array,
        value_array_numeric=value_array_numeric,
        window_start=window_start,
        window_end=window_end,
        observed_at=datetime.now(tz=UTC),
        sensor_instance=sensor_instance,
    )


def _advance_cursor(
    cursor_store: object,
    actor_id: UUID,
    primitive_name: str,
    env: RawMessageEnvelope,
    messages_store: object,
) -> None:
    """Advance the corpus cursor to the current message's position."""
    from eyenet.models._base import new_uuid7  # noqa: PLC0415
    from eyenet.storage.cursors import SQLiteCursorStore  # noqa: PLC0415
    from eyenet.storage.messages import SQLiteMessageStore  # noqa: PLC0415

    if not isinstance(cursor_store, SQLiteCursorStore):
        return

    msg_id: UUID | None = None
    if isinstance(messages_store, SQLiteMessageStore):
        msg_id = messages_store.get_id_by_evidence_ref(env.evidence_ref)

    cursor_store.set(
        actor_id,
        primitive_name,
        env.sent_at_source,
        msg_id or new_uuid7(),
    )


__all__ = ["StylometricSensor"]
