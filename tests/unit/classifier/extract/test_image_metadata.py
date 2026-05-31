"""IMAGE two-pass host logic: Tesseract OCR + best-effort Pillow EXIF, merged.

The real jail/Pillow are not exercised here (that's the real-jail smoke). A
sequenced fake returns one result for the OCR entrypoint pass (worker_path=None)
and another for the EXIF worker pass, so we can assert the merge + the §0
discipline: a failed/absent EXIF pass NEVER fails-closes a readable image, and
metadata is captured even when OCR text is empty.
"""

from __future__ import annotations

import pytest

from eyenet.classifier import extract
from eyenet.classifier.extract import extract_document
from eyenet.classifier.sandbox import ExtractResult, FailedClosed, FailReason, SandboxProfile

pytestmark = pytest.mark.unit

_IMAGE = b"\x89PNG\r\n\x1a\n image"


class _SeqSandbox:
    """Returns `ocr` for the entrypoint pass (worker_path=None), else `exif`."""

    def __init__(
        self, ocr: ExtractResult | FailedClosed, exif: ExtractResult | FailedClosed
    ) -> None:
        self.ocr = ocr
        self.exif = exif
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
        self.calls.append({"worker_path": worker_path, "interpret": interpret})
        return self.ocr if worker_path is None else self.exif


@pytest.fixture
def install(monkeypatch: pytest.MonkeyPatch):
    def _install(ocr: ExtractResult | FailedClosed, exif: ExtractResult | FailedClosed):
        sandbox = _SeqSandbox(ocr, exif)
        monkeypatch.setattr(extract, "extract_sandboxed", sandbox)
        monkeypatch.setattr(extract, "venv_profile", lambda: SandboxProfile(name="venv"))
        monkeypatch.setattr(
            extract,
            "tesseract_profile",
            lambda: SandboxProfile(name="tesseract", entrypoint=("/usr/bin/tesseract",)),
        )
        return sandbox

    return _install


def test_exif_is_merged_into_ocr_meta(install) -> None:
    sandbox = install(
        ExtractResult(text="ocr text", meta={}),
        ExtractResult(text="", meta={"method": "pillow-exif", "exif": {"Make": "Canon"}}),
    )
    result = extract_document(_IMAGE)
    assert isinstance(result, ExtractResult)
    assert result.text == "ocr text"
    assert result.meta["exif"] == {"Make": "Canon"}
    assert result.meta["ocr_applied"] is True
    # Two passes: OCR entrypoint first, then the EXIF worker.
    assert sandbox.calls[0]["worker_path"] is None
    assert sandbox.calls[0]["interpret"] == "raw_text"
    assert str(sandbox.calls[1]["worker_path"]).endswith("image_meta_worker.py")
    assert sandbox.calls[1]["interpret"] == "envelope"


def test_exif_pass_failure_does_not_fail_the_document(install) -> None:
    install(
        ExtractResult(text="ocr text", meta={}),
        FailedClosed(reason=FailReason.BAD_OUTPUT, detail="garbage"),
    )
    result = extract_document(_IMAGE)
    assert isinstance(result, ExtractResult)  # NOT fail-closed — EXIF is best-effort
    assert result.text == "ocr text"
    assert result.meta["exif"] == {}


def test_exif_skipped_when_venv_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    sandbox = _SeqSandbox(
        ExtractResult(text="ocr text", meta={}),
        ExtractResult(text="", meta={"exif": {"Make": "Canon"}}),
    )
    monkeypatch.setattr(extract, "extract_sandboxed", sandbox)
    monkeypatch.setattr(extract, "venv_profile", lambda: None)  # no EXIF worker possible
    monkeypatch.setattr(
        extract,
        "tesseract_profile",
        lambda: SandboxProfile(name="tesseract", entrypoint=("/usr/bin/tesseract",)),
    )
    result = extract_document(_IMAGE)
    assert isinstance(result, ExtractResult)
    assert result.meta["exif"] == {}
    assert len(sandbox.calls) == 1  # EXIF pass never attempted


def test_metadata_captured_even_when_ocr_text_empty(install) -> None:
    install(
        ExtractResult(text="   \n\t", meta={}),
        ExtractResult(text="", meta={"exif": {"Software": "Adobe"}}),
    )
    result = extract_document(_IMAGE)
    assert isinstance(result, ExtractResult)
    assert result.meta["empty"] is True
    assert result.meta["exif"] == {"Software": "Adobe"}


def test_ocr_failure_skips_exif_and_fails_closed(install) -> None:
    sandbox = install(
        FailedClosed(reason=FailReason.PARSER_KILLED, detail="SIGSYS"),
        ExtractResult(text="", meta={"exif": {"Make": "Canon"}}),
    )
    result = extract_document(_IMAGE)
    assert isinstance(result, FailedClosed)
    assert result.reason is FailReason.PARSER_KILLED
    assert len(sandbox.calls) == 1  # EXIF never attempted once OCR fails closed
