"""ClassifierService — the async classification worker (M10 slice 8).

The bus harness around the slice-7 ingest core. CLASSIFIER_PLAN §5: the heavy
OCR+NER+LLM pipeline must run OFF the request/collector path so a 200-page upload
or an adversarial NER pass never blocks ingest. Evidence arrives at a fast entry
point (the upload endpoint, or a collector) that stores the bytes + a provisional
CLASSIFIED row, then publishes a trigger; this service settles the tier:

    classify.document.uploaded  → settle_document(document_id)
    classify.attachment.stored  → classify_attachment(attachment_id)

Plural-from-day-one (§4.6). Fail-closed by construction: a failed settle leaves
the row at its provisional CLASSIFIED tier — safe, and re-drivable on redelivery.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace
from pydantic import ValidationError

from eyenet.classifier.ingest import classify_attachment, settle_document
from eyenet.contracts.classify_events import (
    SUBJECT_ATTACHMENT_STORED,
    SUBJECT_DOCUMENT_UPLOADED,
    AttachmentStoredEnvelope,
    DocumentUploadedEnvelope,
)
from eyenet.service import ServiceBase

if TYPE_CHECKING:
    from eyenet.contracts.bus import Bus
    from eyenet.storage.repository import BaseRepository

from eyenet.telemetry.propagation import attach_from_headers

_tracer = trace.get_tracer("eyenet.classifier")
_log = structlog.get_logger()


class ClassifierService(ServiceBase):
    """Async worker that settles classifier tiers off the bus."""

    def __init__(
        self,
        *,
        bus: Bus,
        storage: BaseRepository,
        instance_id: str = "classifier_1",
    ) -> None:
        super().__init__(bus=bus, storage=storage)
        self._instance_id = instance_id

    @property
    def name(self) -> str:
        return "classifier"

    @property
    def instance_id(self) -> str:
        return self._instance_id

    async def on_subscribe(self) -> None:
        async def _on_document(_subject: str, payload: bytes, headers: dict[str, str]) -> None:
            asyncio.create_task(self._process_document(payload, headers))  # noqa: RUF006

        async def _on_attachment(_subject: str, payload: bytes, headers: dict[str, str]) -> None:
            asyncio.create_task(self._process_attachment(payload, headers))  # noqa: RUF006

        await self._bus.subscribe(SUBJECT_DOCUMENT_UPLOADED, _on_document)
        await self._bus.subscribe(SUBJECT_ATTACHMENT_STORED, _on_attachment)
        _log.info("classifier.subscribed", instance_id=self.instance_id)

    async def _process_document(self, payload: bytes, headers: dict[str, str]) -> None:
        with attach_from_headers(headers):
            try:
                envelope = DocumentUploadedEnvelope.model_validate_json(payload)
            except ValidationError as exc:
                _log.error(
                    "classifier.envelope_parse_error",
                    subject=SUBJECT_DOCUMENT_UPLOADED,
                    error=str(exc),
                )
                return
            with _tracer.start_as_current_span(
                "classifier.settle_document",
                attributes={
                    "service.name": self.name,
                    "service.instance_id": self.instance_id,
                    "document.id": str(envelope.document_id),
                },
            ):
                try:
                    await settle_document(
                        envelope.document_id, storage=self.storage, audit=self.audit
                    )
                except Exception as exc:  # log + leave the row provisional CLASSIFIED (§0)
                    _log.error(
                        "classifier.error",
                        subject=SUBJECT_DOCUMENT_UPLOADED,
                        document_id=str(envelope.document_id),
                        error=str(exc),
                    )

    async def _process_attachment(self, payload: bytes, headers: dict[str, str]) -> None:
        with attach_from_headers(headers):
            try:
                envelope = AttachmentStoredEnvelope.model_validate_json(payload)
            except ValidationError as exc:
                _log.error(
                    "classifier.envelope_parse_error",
                    subject=SUBJECT_ATTACHMENT_STORED,
                    error=str(exc),
                )
                return
            with _tracer.start_as_current_span(
                "classifier.classify_attachment",
                attributes={
                    "service.name": self.name,
                    "service.instance_id": self.instance_id,
                    "attachment.id": str(envelope.attachment_id),
                },
            ):
                try:
                    await classify_attachment(
                        envelope.attachment_id, storage=self.storage, audit=self.audit
                    )
                except Exception as exc:  # log + leave the row provisional CLASSIFIED (§0)
                    _log.error(
                        "classifier.error",
                        subject=SUBJECT_ATTACHMENT_STORED,
                        attachment_id=str(envelope.attachment_id),
                        error=str(exc),
                    )


__all__ = ["ClassifierService"]
