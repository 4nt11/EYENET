"""ingest_document(): the full-pipeline-at-upload orchestration core.

The jailed stages (``extract_document``, ``detect``) are faked so the chain runs
without nsjail; the real ``classify`` + ``aggregate`` bind the tier, and the LLM
is injected. Asserts the settled tier, persistence, §0 fail-closed, host-side
metadata sanitization, the empty-text-still-captures-metadata rule, and audit
emission with a redacted payload.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from eyenet.classifier import ingest as ingest_mod
from eyenet.classifier.ingest import ingest_document
from eyenet.classifier.llm import LlmAdvisory, LlmUnavailable
from eyenet.classifier.presidio import PresidioVerdict
from eyenet.classifier.sandbox import ExtractResult, FailedClosed, FailReason
from eyenet.contracts.enums import SensitivityTier
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

N = SensitivityTier.NORMAL
R = SensitivityTier.RESTRICTED
C = SensitivityTier.CLASSIFIED

_BENIGN = "just a friendly note about lunch plans"


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _normal_presidio() -> PresidioVerdict:
    return PresidioVerdict(tier_floor=N, matches=(), map_version="v1")


class _FakeAudit:
    """Duck-typed AuditEmitter — records emit calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def emit(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


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


async def _advise_higher(text: str) -> LlmAdvisory:
    return LlmAdvisory(
        suggested_tier=R, summary="looks sensitive", indicators=("x",), confidence="high"
    )


async def test_benign_doc_settles_normal_and_persists(
    storage: BaseRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, extraction=ExtractResult(text=_BENIGN, meta={"doc_kind": "text"}))
    result = await ingest_document(
        b"raw bytes",
        storage=storage,
        data_dir=tmp_path,
        filename="note.txt",
        mime="text/plain",
        advise_fn=_advise_normal,
    )
    assert result.verdict.tier is N
    row = await storage.get_document(result.document_id)
    assert row is not None
    assert row.classifier_tier is N
    assert row.doc_kind == "text"
    assert row.mime == "text/plain"
    assert row.sha256 == result.sha256
    assert row.extracted_text == _BENIGN
    assert row.review_required is False


async def test_failed_extraction_settles_classified(
    storage: BaseRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(
        monkeypatch,
        extraction=FailedClosed(reason=FailReason.PARSER_KILLED, detail="SIGSYS"),
    )

    # advise_fn must NOT be consulted when fail_closed; a raising stub proves it.
    async def _boom(text: str) -> LlmAdvisory:
        raise AssertionError("LLM must not be consulted on a fail-closed doc")

    result = await ingest_document(b"hostile", storage=storage, data_dir=tmp_path, advise_fn=_boom)
    assert result.verdict.tier is C
    assert result.verdict.fail_closed is True
    row = await storage.get_document(result.document_id)
    assert row is not None
    assert row.classifier_tier is C
    assert row.extracted_text is None


async def test_hostile_embedded_metadata_is_sanitized(
    storage: BaseRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = {
        "doc_kind": "pdf",
        "embedded": {"author": "<script>alert(1)</script>", "producer": "ok & fine"},
    }
    _install(monkeypatch, extraction=ExtractResult(text=_BENIGN, meta=meta))
    result = await ingest_document(
        b"x", storage=storage, data_dir=tmp_path, advise_fn=_advise_normal
    )
    row = await storage.get_document(result.document_id)
    assert row is not None
    embedded = row.embedded_meta["embedded"]
    assert isinstance(embedded, dict)
    assert "<script>" not in embedded["author"]
    assert "&lt;script&gt;" in embedded["author"]
    assert "&amp;" in embedded["producer"]


async def test_metadata_list_scalar_and_exotic_values_sanitized(
    storage: BaseRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # EXIF often yields list values (tuples) + numeric scalars; an exotic type
    # (e.g. bytes) must coerce to a sanitized string, never crash.
    meta: dict[str, object] = {
        "exif": {
            "tags": ["<b>x</b>", "plain"],  # list of strings
            "Orientation": 6,  # numeric scalar passthrough
            "Raw": b"\x00bytes",  # exotic -> str -> sanitized
        }
    }
    _install(monkeypatch, extraction=ExtractResult(text=_BENIGN, meta=meta))
    result = await ingest_document(
        b"img", storage=storage, data_dir=tmp_path, advise_fn=_advise_normal
    )
    row = await storage.get_document(result.document_id)
    assert row is not None
    exif = row.embedded_meta["exif"]
    assert isinstance(exif, dict)
    assert exif["tags"] == ["&lt;b&gt;x&lt;/b&gt;", "plain"]
    assert exif["Orientation"] == 6
    assert isinstance(exif["Raw"], str)  # coerced, not bytes


async def test_metadata_captured_when_text_empty(
    storage: BaseRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = {"doc_kind": "image", "exif": {"Make": "Canon"}}
    _install(monkeypatch, extraction=ExtractResult(text="", meta=meta))
    result = await ingest_document(
        b"img", storage=storage, data_dir=tmp_path, advise_fn=_advise_normal
    )
    row = await storage.get_document(result.document_id)
    assert row is not None
    assert row.embedded_meta["exif"] == {"Make": "Canon"}
    assert row.extracted_text is None  # empty text stored as None, metadata kept


async def test_audit_emitted_with_redacted_payload(
    storage: BaseRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, extraction=ExtractResult(text=_BENIGN, meta={"doc_kind": "text"}))
    audit = _FakeAudit()
    result = await ingest_document(
        b"x", storage=storage, data_dir=tmp_path, audit=audit, advise_fn=_advise_normal
    )
    assert len(audit.calls) == 1  # aggregated only (no review flags)
    call = audit.calls[0]
    assert call["subject_kind"] == "document"
    assert call["subject_id"] == result.document_id
    assert call["evidence_ref"] == f"document:{result.document_id}"
    payload = call["payload"]
    assert isinstance(payload, dict)
    # No LLM free-text summary in the (non-clearance-gated) audit payload.
    if "llm" in payload:
        assert "summary" not in payload["llm"]


async def test_llm_higher_tier_flags_and_emits_review(
    storage: BaseRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, extraction=ExtractResult(text=_BENIGN, meta={"doc_kind": "text"}))
    audit = _FakeAudit()
    result = await ingest_document(
        b"x", storage=storage, data_dir=tmp_path, audit=audit, advise_fn=_advise_higher
    )
    # Tier NEVER moves — flag only.
    assert result.verdict.tier is N
    assert result.verdict.review_flags
    row = await storage.get_document(result.document_id)
    assert row is not None
    assert row.review_required is True
    events = [c["event"] for c in audit.calls]
    assert len(events) == 2  # aggregated + review_flagged


async def test_no_audit_emitter_is_fine(
    storage: BaseRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, extraction=ExtractResult(text=_BENIGN, meta={}))
    result = await ingest_document(
        b"x", storage=storage, data_dir=tmp_path, advise_fn=_advise_normal
    )
    assert await storage.get_document(result.document_id) is not None


async def test_unhandled_stage_error_persists_no_row(
    storage: BaseRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _explode(blob: bytes) -> ExtractResult:
        raise RuntimeError("extractor blew up")

    monkeypatch.setattr(ingest_mod, "extract_document", _explode)
    calls: list[object] = []
    original = storage.put_document

    async def _spy(row: object) -> UUID:
        calls.append(row)
        return await original(row)

    monkeypatch.setattr(storage, "put_document", _spy)
    with pytest.raises(RuntimeError, match="blew up"):
        await ingest_document(b"x", storage=storage, data_dir=tmp_path, advise_fn=_advise_normal)
    assert calls == []  # never reached persistence


def test_llm_unavailable_outcome_is_importable() -> None:
    # Guard: the merge path also handles LlmUnavailable (covered in aggregate tests).
    assert LlmUnavailable(reason="down", detail="", attempts=0).reason == "down"
