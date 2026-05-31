"""The async orchestration seams: stage_document / settle_document /
classify_attachment / classify_blob.

The jailed stages (``extract_document``, ``detect``) are faked so the chain runs
without nsjail; bytes round-trip through the real on-disk stores under tmp_path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eyenet.classifier import ingest as ingest_mod
from eyenet.classifier.ingest import (
    classify_attachment,
    classify_blob,
    settle_document,
    stage_document,
)
from eyenet.classifier.llm import LlmAdvisory
from eyenet.classifier.presidio import PresidioVerdict
from eyenet.classifier.sandbox import ExtractResult, FailedClosed, FailReason
from eyenet.contracts.enums import AttachmentKind, SensitivityTier, SourceKind
from eyenet.contracts.message import AttachmentRow
from eyenet.storage.attachments import store_attachment
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

N = SensitivityTier.NORMAL
R = SensitivityTier.RESTRICTED
C = SensitivityTier.CLASSIFIED

_BENIGN = "a friendly note about lunch plans"


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _normal_presidio() -> PresidioVerdict:
    return PresidioVerdict(tier_floor=N, matches=(), map_version="v1")


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    extraction: ExtractResult | FailedClosed,
    presidio: PresidioVerdict | None = None,
) -> None:
    monkeypatch.setattr(ingest_mod, "extract_document", lambda blob: extraction)
    monkeypatch.setattr(ingest_mod, "detect", lambda text: presidio or _normal_presidio())


async def _advise_normal(text: str) -> LlmAdvisory:
    return LlmAdvisory(suggested_tier=N, summary="benign", indicators=(), confidence="low")


class _FakeAudit:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def emit(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


# --- classify_blob (pure pipeline) ------------------------------------------


async def test_classify_blob_returns_settled_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, extraction=ExtractResult(text=_BENIGN, meta={"doc_kind": "text"}))
    out = await classify_blob(b"raw", advise_fn=_advise_normal)
    assert out.verdict.tier is N
    assert out.text == _BENIGN
    assert out.doc_kind == "text"


async def test_classify_blob_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, extraction=FailedClosed(reason=FailReason.PARSER_KILLED, detail="x"))

    async def _boom(text: str) -> LlmAdvisory:
        raise AssertionError("LLM must not run on fail-closed")

    out = await classify_blob(b"hostile", advise_fn=_boom)
    assert out.verdict.tier is C
    assert out.verdict.fail_closed is True
    assert out.text == ""


# --- stage_document → provisional ; settle_document → settled ---------------


async def test_stage_then_settle_round_trip(
    storage: BaseRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # stage uses the REAL store_document (writes bytes under tmp_path); settle
    # reads them back. Only the jailed pipeline is faked.
    _install(monkeypatch, extraction=ExtractResult(text=_BENIGN, meta={"doc_kind": "text"}))
    blob = b"lunch plans for friday"
    doc_id, sha256 = await stage_document(
        blob, storage=storage, data_dir=tmp_path, filename="n.txt", mime="text/plain"
    )

    provisional = await storage.get_document(doc_id)
    assert provisional is not None
    assert provisional.classifier_tier is C  # born CLASSIFIED, §0 fail-closed
    assert provisional.extracted_text is None
    assert provisional.sha256 == sha256

    audit = _FakeAudit()
    verdict = await settle_document(doc_id, storage=storage, audit=audit, advise_fn=_advise_normal)
    assert verdict.tier is N

    settled = await storage.get_document(doc_id)
    assert settled is not None
    assert settled.classifier_tier is N  # provisional → settled (lowered)
    assert settled.extracted_text == _BENIGN
    assert settled.doc_kind == "text"
    assert len(audit.calls) == 1
    assert audit.calls[0]["subject_kind"] == "document"


async def test_settle_missing_document_raises(storage: BaseRepository) -> None:
    from uuid import uuid4

    with pytest.raises(ValueError, match="not found"):
        await settle_document(uuid4(), storage=storage, advise_fn=_advise_normal)


async def test_settle_failed_extraction_stays_classified(
    storage: BaseRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, extraction=ExtractResult(text=_BENIGN, meta={"doc_kind": "text"}))
    doc_id, _ = await stage_document(b"x", storage=storage, data_dir=tmp_path)
    # Now make the pipeline fail closed at settle time.
    _install(monkeypatch, extraction=FailedClosed(reason=FailReason.TIMEOUT, detail="slow"))
    verdict = await settle_document(doc_id, storage=storage, advise_fn=_advise_normal)
    assert verdict.tier is C
    settled = await storage.get_document(doc_id)
    assert settled is not None
    assert settled.classifier_tier is C


# --- classify_attachment → stamps AttachmentTable ---------------------------


async def test_classify_attachment_stamps_tier(
    storage: BaseRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, extraction=ExtractResult(text=_BENIGN, meta={"doc_kind": "text"}))
    blob = b"benign attachment bytes"
    _, storage_uri = store_attachment(
        tmp_path, blob, source=SourceKind.TELEGRAM, instance_id="abcd1234"
    )
    from uuid import uuid4

    aid = await storage.put_attachment(
        AttachmentRow(
            message_id=uuid4(),
            kind=AttachmentKind.DOCUMENT,
            mime="text/plain",
            size_bytes=len(blob),
            sha256="c" * 64,
            storage_uri=storage_uri,
            classifier_tier=C,  # provisional at collector insert
        )
    )

    audit = _FakeAudit()
    verdict = await classify_attachment(aid, storage=storage, audit=audit, advise_fn=_advise_normal)
    assert verdict.tier is N

    got = await storage.get_attachment(aid)
    assert got is not None
    assert got.classifier_tier is N  # provisional CLASSIFIED → settled NORMAL
    assert audit.calls[0]["subject_kind"] == "attachment"
    assert audit.calls[0]["evidence_ref"] == f"attachment:{aid}"


async def test_classify_attachment_missing_raises(storage: BaseRepository) -> None:
    from uuid import uuid4

    with pytest.raises(ValueError, match="not found"):
        await classify_attachment(uuid4(), storage=storage, advise_fn=_advise_normal)
