"""Dispatch logic: sniff -> profile + worker -> chokepoint -> normalized result.

The real nsjail is not exercised here — a fake sandbox records how each document
kind is routed (worker, interpretation) and returns a canned outcome. The cage
itself is proven in the real-nsjail integration suite.
"""

from __future__ import annotations

import pytest

from eyenet.classifier import extract
from eyenet.classifier.extract import DocKind, extract_document
from eyenet.classifier.sandbox import ExtractResult, FailedClosed, FailReason, SandboxProfile

pytestmark = pytest.mark.unit

_PDF = b"%PDF-1.7 body"
_DOCX = b"PK\x03\x04 zip body"
_TEXT = b"plain prose"
_RTF = b"{\\rtf1 hi}"
_HTML = b"<html>hi</html>"
_IMAGE = b"\x89PNG\r\n\x1a\n image"
_UNKNOWN = b"\x00\x01\x02 binary"


class _FakeSandbox:
    """Records each chokepoint call and returns a configured outcome."""

    def __init__(self, result: ExtractResult | FailedClosed) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        blob: bytes,
        *,
        worker_path: str | None = None,
        worker_args: object = (),
        limits: object = None,
        profile: SandboxProfile | None = None,
        interpret: str = "envelope",
    ) -> ExtractResult | FailedClosed:
        self.calls.append(
            {"blob": blob, "worker_path": worker_path, "profile": profile, "interpret": interpret}
        )
        return self.result


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch):
    """Patch the chokepoint + profile builders so any kind reaches the sandbox."""

    def _install(result: ExtractResult | FailedClosed) -> _FakeSandbox:
        sandbox = _FakeSandbox(result)
        monkeypatch.setattr(extract, "extract_sandboxed", sandbox)
        monkeypatch.setattr(extract, "venv_profile", lambda: SandboxProfile(name="venv"))
        monkeypatch.setattr(
            extract,
            "tesseract_profile",
            lambda: SandboxProfile(name="tesseract", entrypoint=("/usr/bin/tesseract",)),
        )
        return sandbox

    return _install


def test_text_routes_to_text_worker_envelope(fake) -> None:
    sandbox = fake(ExtractResult(text="prose", meta={"method": "text"}))
    result = extract_document(_TEXT)
    assert isinstance(result, ExtractResult)
    call = sandbox.calls[0]
    assert str(call["worker_path"]).endswith("text_worker.py")
    assert call["interpret"] == "envelope"


@pytest.mark.parametrize(
    ("blob", "worker_suffix"),
    [
        (_PDF, "pdf_worker.py"),
        (_DOCX, "docx_worker.py"),
        (_RTF, "rtf_worker.py"),
        (_HTML, "html_worker.py"),
    ],
)
def test_each_kind_routes_to_its_worker(fake, blob: bytes, worker_suffix: str) -> None:
    sandbox = fake(ExtractResult(text="x", meta={}))
    extract_document(blob)
    assert str(sandbox.calls[0]["worker_path"]).endswith(worker_suffix)
    assert sandbox.calls[0]["interpret"] == "envelope"


def test_image_routes_to_tesseract_raw_text(fake) -> None:
    sandbox = fake(ExtractResult(text="ocr text", meta={}))
    extract_document(_IMAGE)
    call = sandbox.calls[0]
    assert call["worker_path"] is None  # no Python worker; Tesseract is the entrypoint
    assert call["interpret"] == "raw_text"


def test_unknown_blob_fails_closed_without_touching_sandbox(fake) -> None:
    sandbox = fake(ExtractResult(text="should not be used", meta={}))
    result = extract_document(_UNKNOWN)
    assert isinstance(result, FailedClosed)
    assert result.reason is FailReason.UNSUPPORTED_TYPE
    assert sandbox.calls == []


def test_missing_venv_fails_closed_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[object] = []
    monkeypatch.setattr(extract, "extract_sandboxed", lambda *a, **k: called.append(1))
    monkeypatch.setattr(extract, "venv_profile", lambda: None)
    result = extract_document(_PDF)
    assert isinstance(result, FailedClosed)
    assert result.reason is FailReason.EXTRACTOR_UNAVAILABLE
    assert called == []  # never reached the sandbox


def test_missing_tesseract_fails_closed_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract, "tesseract_profile", lambda: None)
    result = extract_document(_IMAGE)
    assert isinstance(result, FailedClosed)
    assert result.reason is FailReason.EXTRACTOR_UNAVAILABLE


def test_failed_closed_from_sandbox_passes_through(fake) -> None:
    fake(FailedClosed(reason=FailReason.PARSER_KILLED, detail="SIGSYS"))
    result = extract_document(_TEXT)
    assert isinstance(result, FailedClosed)
    assert result.reason is FailReason.PARSER_KILLED


def test_meta_is_normalized_with_flags(fake) -> None:
    fake(ExtractResult(text="classified", meta={"method": "text"}))
    result = extract_document(_TEXT)
    assert isinstance(result, ExtractResult)
    assert result.meta["doc_kind"] == DocKind.TEXT.value
    assert result.meta["ocr_applied"] is False
    assert result.meta["empty"] is False
    assert result.meta["method"] == "text"  # worker-supplied provenance preserved


def test_empty_extraction_is_flagged(fake) -> None:
    fake(ExtractResult(text="   \n\t", meta={}))
    result = extract_document(_TEXT)
    assert isinstance(result, ExtractResult)
    assert result.meta["empty"] is True


def test_image_marks_ocr_applied(fake) -> None:
    fake(ExtractResult(text="ocr", meta={}))
    result = extract_document(_IMAGE)
    assert isinstance(result, ExtractResult)
    assert result.meta["ocr_applied"] is True
