"""IncidentClassifierService — batched incident detection off the message bus.

Subscribes to ``raw.message.>``, buffers arriving envelopes, and flushes a batch when
the buffer reaches ``batch_size`` OR the periodic ``tick()`` fires (``flush_interval``),
whichever comes first. Each flush is exactly THREE round-trips regardless of batch size:
one bulk body fetch, one calibrated ``classify_batch``, one ``put_incidents_bulk``. Only
messages with >=1 fired label are stored (``none`` is the ~majority and is dropped).

Design notes / v1 simplifications (see development/incident-classifier-bus-integration-scope.md):
  - Trace: batching decouples arrival from processing, so the per-message
    ``attach_from_headers`` span model does not hold across a flush. Per-message span
    links are future work; the flush audits each fired detection individually.
  - Inference runs off the event loop in a dedicated single-thread executor, so a flush
    never blocks the bus handler; the pool's one worker serializes inference so
    concurrent flushes cannot race the single CUDA model.
  - Audit: a detection (a fired incident) is the operator-relevant event and is audited;
    routine non-firing scans are not (mass-scan != targeted evidence access).
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from eyenet.contracts.incident import IncidentRow
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.incidents import classifier
from eyenet.service.base import ServiceBase
from eyenet.telemetry import get_logger

_log = get_logger()
_DEFAULT_BATCH = 32
_DEFAULT_FLUSH_S = 1.0


class IncidentClassifierService(ServiceBase):
    """Buffered, batched incident classifier service."""

    def __init__(
        self,
        *,
        bus: object,
        storage: object,
        batch_size: int = _DEFAULT_BATCH,
        flush_interval: float = _DEFAULT_FLUSH_S,
    ) -> None:
        super().__init__(bus=bus, storage=storage)  # type: ignore[arg-type]
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._buffer: list[str] = []  # evidence_refs awaiting classification
        self._lock = asyncio.Lock()
        self._model_version = classifier.model_dir().name
        # Inference runs OFF the event loop in a single dedicated thread: torch releases
        # the GIL during compute so the bus handler keeps buffering, and max_workers=1
        # serializes inference so concurrent flushes never race the one CUDA model.
        self._infer_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="incident-infer")

    @property
    def name(self) -> str:
        return "incident_classifier"

    @property
    def instance_id(self) -> str:
        return f"{self.name}_1"

    async def on_subscribe(self) -> None:
        async def _handler(_subject: str, payload: bytes, _headers: dict[str, str]) -> None:
            try:
                env = RawMessageEnvelope.model_validate_json(payload)
            except Exception as exc:  # malformed envelope: log + drop, never crash the bus
                _log.error("incident.envelope_parse_error", error=str(exc))
                return
            async with self._lock:
                self._buffer.append(env.evidence_ref)
                ready = len(self._buffer) >= self._batch_size
            if ready:
                await self._flush()

        await self._bus.subscribe("raw.message.>", _handler, queue_group="incident")

    async def tick(self) -> None:
        """Time-based flush so low-traffic messages don't wait for a full batch."""
        await self._flush()

    async def shutdown(self) -> None:
        """Flush any buffered messages, then tear down the inference pool."""
        await self._flush()
        await super().shutdown()
        self._infer_pool.shutdown(wait=False, cancel_futures=True)

    async def _flush(self) -> None:
        async with self._lock:
            if not self._buffer:
                return
            refs = list(dict.fromkeys(self._buffer))  # dedup, preserve arrival order
            self._buffer.clear()

        # Heavy work OUTSIDE the lock so the handler keeps accepting messages.
        by_ref = await self._storage.messages_by_evidence_refs(refs)
        ordered = [(ref, by_ref[ref]) for ref in refs if ref in by_ref]
        if not ordered:
            return
        texts = [body for _, (_mid, body) in ordered]
        loop = asyncio.get_running_loop()
        scored = await loop.run_in_executor(self._infer_pool, classifier.classify_batch, texts)

        now = datetime.now(UTC)
        rows: list[object] = []
        for (ref, (mid, _body)), scores, text in zip(ordered, scored, texts, strict=True):
            fired = {s.label for s in scores if s.fired} | classifier.prefilter_labels(text)
            if not fired:
                continue
            rows.append(
                IncidentRow(
                    message_id=mid,
                    labels=[s.label for s in scores if s.label in fired],  # head order
                    scores={s.label: s.prob for s in scores},
                    model_version=self._model_version,
                    classified_at=now,
                )
            )
            await self.audit.emit(
                event="incident_detected",
                subject_kind="evidence",
                payload={
                    "evidence_ref": ref,
                    "labels": sorted(fired),
                    "reason": "incident_classification",
                },
            )

        if rows:
            await self._storage.put_incidents_bulk(rows)
        _log.info("incident.flush", scanned=len(ordered), fired=len(rows))


__all__ = ["IncidentClassifierService"]
