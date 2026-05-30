"""End-to-end extraction against the REAL nsjail + parser libraries.

These prove the adapters actually parse real documents inside the cage. The
stdlib formats (text/rtf/html) only need nsjail; the PDF/DOCX/OCR cases need the
dedicated ``eyenet-extract`` venv (point ``EYENET_EXTRACT_VENV`` at it) and, for
OCR, the ``tesseract`` binary. Fixtures are generated with the venv's own
libraries so the documents are guaranteed valid.
"""

from __future__ import annotations

import shutil

# Controlled argv (venv python + constant generator code); shell=False.
import subprocess  # nosec B404
from collections.abc import Iterator
from pathlib import Path

import pytest

from eyenet.classifier.extract import extract_document
from eyenet.classifier.sandbox import (
    ExtractResult,
    FailedClosed,
    FailReason,
    SandboxLimits,
    _chokepoint as cp,
    arm_sandbox,
    reset_sandbox,
    resolve_extract_venv,
    sandbox_state,
)
from eyenet.classifier.sandbox._profiles import venv_site_packages

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("nsjail") is None, reason="nsjail not installed"),
]

_VENV = resolve_extract_venv()
_HAVE_VENV = _VENV is not None and venv_site_packages(_VENV) is not None
_HAVE_TESS = shutil.which("tesseract") is not None
_needs_venv = pytest.mark.skipif(not _HAVE_VENV, reason="eyenet-extract venv not built")
_needs_tess = pytest.mark.skipif(not _HAVE_TESS, reason="tesseract not installed")

# PDF render / OCR need more than the snappy 2s used for pure-Python probes.
_LIMITS = SandboxLimits(time_limit_s=10, parent_timeout_s=15)


@pytest.fixture(autouse=True)
def _armed() -> Iterator[None]:
    reset_sandbox()
    arm_sandbox(limits=_LIMITS, force=True)
    assert sandbox_state() is cp.SandboxState.HEALTHY
    yield
    reset_sandbox()


def _gen(out: Path, code: str) -> bytes:
    """Run the venv python to generate a real document; return its bytes."""
    venv_python = str(_VENV / "bin" / "python")  # type: ignore[operator]
    subprocess.run([venv_python, "-c", code, str(out)], check=True)  # noqa: S603
    return out.read_bytes()


# ---- stdlib formats (no venv needed) --------------------------------------


def test_real_text_extraction() -> None:
    result = extract_document(b"OPERATION NIGHTFALL is classified")
    assert isinstance(result, ExtractResult)
    assert "NIGHTFALL" in result.text
    assert result.meta["doc_kind"] == "text"
    assert result.meta["empty"] is False


def test_real_html_extraction() -> None:
    blob = b"<html><body><script>x=1</script><p>SECRET cable</p></body></html>"
    result = extract_document(blob)
    assert isinstance(result, ExtractResult)
    assert "SECRET cable" in result.text
    assert "x=1" not in result.text  # script content dropped


def test_real_rtf_extraction() -> None:
    blob = rb"{\rtf1\ansi\deff0 {\fonttbl{\f0 Arial;}}\f0 CLASSIFIED memo text}"
    result = extract_document(blob)
    assert isinstance(result, ExtractResult)
    assert "CLASSIFIED memo text" in result.text


def test_real_unknown_blob_fails_closed() -> None:
    result = extract_document(b"\x00\x01\x02\x03 not any known format")
    assert isinstance(result, FailedClosed)
    assert result.reason is FailReason.UNSUPPORTED_TYPE


# ---- venv-backed formats --------------------------------------------------


@_needs_venv
def test_real_pdf_text_layer(tmp_path: Path) -> None:
    blob = _gen(
        tmp_path / "doc.pdf",
        "import sys, fitz; d=fitz.open(); p=d.new_page();"
        " p.insert_text((72,72),'CLASSIFIED DOSSIER ALPHA'); d.save(sys.argv[1])",
    )
    result = extract_document(blob, limits=_LIMITS)
    assert isinstance(result, ExtractResult), result
    assert "CLASSIFIED DOSSIER ALPHA" in result.text
    assert result.meta["method"] == "pymupdf"
    assert result.meta["doc_kind"] == "pdf"


@_needs_venv
def test_real_docx_text(tmp_path: Path) -> None:
    blob = _gen(
        tmp_path / "doc.docx",
        "import sys, docx; d=docx.Document();"
        " d.add_paragraph('CLASSIFIED DOSSIER BRAVO'); d.save(sys.argv[1])",
    )
    result = extract_document(blob, limits=_LIMITS)
    assert isinstance(result, ExtractResult), result
    assert "CLASSIFIED DOSSIER BRAVO" in result.text
    assert result.meta["method"] == "python-docx"


@_needs_venv
def test_real_encrypted_pdf_fails_closed(tmp_path: Path) -> None:
    blob = _gen(
        tmp_path / "enc.pdf",
        "import sys, fitz; d=fitz.open(); d.new_page();"
        " d.save(sys.argv[1], encryption=fitz.PDF_ENCRYPT_AES_256,"
        " owner_pw='o', user_pw='locked')",
    )
    result = extract_document(blob, limits=_LIMITS)
    assert isinstance(result, FailedClosed)
    assert result.reason is FailReason.PARSER_CRASH


@_needs_venv
def test_real_corrupt_docx_fails_closed() -> None:
    # Sniffs as ZIP_OOXML (PK..) but python-docx rejects it. The error path either
    # exits non-zero (PARSER_CRASH) or trips a syscall outside the tight allowlist
    # (PARSER_KILLED) — both are contained fail-closed, which is the guarantee.
    result = extract_document(b"PK\x03\x04 not really a docx", limits=_LIMITS)
    assert isinstance(result, FailedClosed)
    assert result.reason in (FailReason.PARSER_CRASH, FailReason.PARSER_KILLED)


@_needs_venv
@_needs_tess
def test_real_image_ocr(tmp_path: Path) -> None:
    blob = _gen(
        tmp_path / "scan.png",
        "import sys, fitz; d=fitz.open(); p=d.new_page();"
        " p.insert_text((40,80),'SECRET OCR ALPHA', fontsize=40);"
        " p.get_pixmap(dpi=200).save(sys.argv[1])",
    )
    result = extract_document(blob, limits=_LIMITS)
    assert isinstance(result, ExtractResult), result
    assert "SECRET" in result.text.upper()
    assert result.meta["ocr_applied"] is True
    assert result.meta["doc_kind"] == "image"
