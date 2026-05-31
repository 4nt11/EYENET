"""ClassifierService — the async bus harness around the ingest core.

Drives the service through a MemoryBus exactly as production does: publish a
trigger, let the create_task'd handler run (asyncio.sleep), assert the storage
side effect. The jailed pipeline (extract_document/detect) + advise are stubbed
so the path is deterministic and network-free.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
import structlog

from eyenet.bus import MemoryBus
from eyenet.classifier import ingest as ingest_mod
from eyenet.classifier.llm import LlmAdvisory
from eyenet.classifier.presidio import PresidioVerdict
from eyenet.classifier.sandbox import ExtractResult, FailedClosed, FailReason
from eyenet.classifier.service import ClassifierService
from eyenet.contracts._base import TraceContext
from eyenet.contracts.classify_events import (
    SUBJECT_ATTACHMENT_STORED,
    SUBJECT_DOCUMENT_UPLOADED,
    AttachmentStoredEnvelope,
    DocumentUploadedEnvelope,
)
from eyenet.contracts.enums import AttachmentKind, SensitivityTier, SourceKind
from eyenet.contracts.message import AttachmentRow
from eyenet.storage.attachments import store_attachment
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

N = SensitivityTier.NORMAL
C = SensitivityTier.CLASSIFIED

_TRACEPARENT = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
_BENIGN = "a friendly note about lunch plans"


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    structlog.reset_defaults()
    yield
    structlog.reset_defaults()


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _trace() -> TraceContext:
    return TraceContext(traceparent=_TRACEPARENT)


def _install(monkeypatch: pytest.MonkeyPatch, *, extraction: object) -> None:
    monkeypatch.setattr(ingest_mod, "extract_document", lambda blob: extraction)
    monkeypatch.setattr(
        ingest_mod,
        "detect",
        lambda text: PresidioVerdict(tier_floor=N, matches=(), map_version="v1"),
    )

    async def _advise(text: str) -> LlmAdvisory:
        return LlmAdvisory(suggested_tier=N, summary="benign", indicators=(), confidence="low")

    monkeypatch.setattr(ingest_mod, "advise", _advise)


async def _publish_and_drain(bus: MemoryBus, subject: str, envelope: object) -> None:
    await bus.publish(subject, envelope.model_dump_json().encode())  # type: ignore[attr-defined]
    await asyncio.sleep(0.05)  # let the create_task'd handler finish


async def test_document_uploaded_settles_tier(
    storage: BaseRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, extraction=ExtractResult(text=_BENIGN, meta={"doc_kind": "text"}))
    doc_id, _ = await ingest_mod.stage_document(b"lunch plans", storage=storage, data_dir=tmp_path)
    assert (await storage.get_document(doc_id)).classifier_tier is C  # type: ignore[union-attr]

    bus = MemoryBus()
    svc = ClassifierService(bus=bus, storage=storage)
    await svc.on_subscribe()
    await _publish_and_drain(
        bus,
        SUBJECT_DOCUMENT_UPLOADED,
        DocumentUploadedEnvelope(document_id=doc_id, trace_context=_trace()),
    )

    settled = await storage.get_document(doc_id)
    assert settled is not None
    assert settled.classifier_tier is N  # provisional CLASSIFIED → settled NORMAL (real tier)
    assert settled.extracted_text == _BENIGN


async def test_document_uploaded_fail_closed_stays_classified(
    storage: BaseRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, extraction=ExtractResult(text=_BENIGN, meta={"doc_kind": "text"}))
    doc_id, _ = await ingest_mod.stage_document(b"x", storage=storage, data_dir=tmp_path)
    # Pipeline fails closed at settle time → tier stays CLASSIFIED.
    _install(monkeypatch, extraction=FailedClosed(reason=FailReason.PARSER_KILLED, detail="boom"))

    bus = MemoryBus()
    svc = ClassifierService(bus=bus, storage=storage)
    await svc.on_subscribe()
    await _publish_and_drain(
        bus,
        SUBJECT_DOCUMENT_UPLOADED,
        DocumentUploadedEnvelope(document_id=doc_id, trace_context=_trace()),
    )

    row = await storage.get_document(doc_id)
    assert row is not None
    assert row.classifier_tier is C


async def test_attachment_stored_stamps_tier(
    storage: BaseRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, extraction=ExtractResult(text=_BENIGN, meta={"doc_kind": "text"}))
    blob = b"benign attachment"
    sha, uri = store_attachment(tmp_path, blob, source=SourceKind.TELEGRAM, instance_id="abcd1234")
    msg_id = uuid4()
    aid = await storage.put_attachment(
        AttachmentRow(
            message_id=msg_id,
            kind=AttachmentKind.DOCUMENT,
            mime="text/plain",
            size_bytes=len(blob),
            sha256=sha,
            storage_uri=uri,
            classifier_tier=C,
        )
    )

    bus = MemoryBus()
    svc = ClassifierService(bus=bus, storage=storage)
    await svc.on_subscribe()
    await _publish_and_drain(
        bus,
        SUBJECT_ATTACHMENT_STORED,
        AttachmentStoredEnvelope(
            attachment_id=aid,
            message_id=msg_id,
            storage_uri=uri,
            sha256=sha,
            mime="text/plain",
            trace_context=_trace(),
        ),
    )

    got = await storage.get_attachment(aid)
    assert got is not None
    assert got.classifier_tier is N  # provisional CLASSIFIED → settled NORMAL


async def test_unparseable_payload_logs_and_does_not_crash(
    storage: BaseRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus = MemoryBus()
    svc = ClassifierService(bus=bus, storage=storage)
    await svc.on_subscribe()
    with structlog.testing.capture_logs() as caplog:
        await bus.publish(SUBJECT_DOCUMENT_UPLOADED, b"{not json")
        await asyncio.sleep(0.05)
    events = [r["event"] for r in caplog]
    assert "classifier.envelope_parse_error" in events


async def test_settle_error_is_logged_not_raised(
    storage: BaseRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A document_id that does not exist → settle_document raises ValueError;
    # the handler must log classifier.error and not crash the service loop.
    bus = MemoryBus()
    svc = ClassifierService(bus=bus, storage=storage)
    await svc.on_subscribe()
    with structlog.testing.capture_logs() as caplog:
        await bus.publish(
            SUBJECT_DOCUMENT_UPLOADED,
            DocumentUploadedEnvelope(document_id=uuid4(), trace_context=_trace())
            .model_dump_json()
            .encode(),
        )
        await asyncio.sleep(0.05)
    events = [r["event"] for r in caplog]
    assert "classifier.error" in events


def test_service_identity() -> None:
    svc = ClassifierService(bus=MemoryBus(), storage=get_repository(in_memory=True))
    assert svc.name == "classifier"
    assert svc.instance_id == "classifier_1"
    svc2 = ClassifierService(
        bus=MemoryBus(), storage=get_repository(in_memory=True), instance_id="classifier_7"
    )
    assert svc2.instance_id == "classifier_7"
