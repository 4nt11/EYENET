"""Smoke tests over committed REAL files from diverse producers.

Unlike ``test_extract_real`` (which generates documents with the same library
that reads them), these fixtures were produced by *different* engines than the
parsers — PDF by LibreOffice (not fitz), DOCX/RTF by pandoc (not python-docx),
PNG by ImageMagick (not a fitz pixmap). That breaks the writer==reader
self-reference and anchors the bytes for regression. All files are small and
innocuous; each carries an ``EYENET SMOKE <FMT>`` marker.

Gated like the rest of the real-jail suite: nsjail is required; PDF/DOCX add the
``eyenet-extract`` venv; OCR adds the ``tesseract`` binary.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from eyenet.classifier.extract import extract_document
from eyenet.classifier.sandbox import (
    ExtractResult,
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

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "classifier"
_LIMITS = SandboxLimits(time_limit_s=10, parent_timeout_s=15)


@pytest.fixture(autouse=True)
def _armed() -> Iterator[None]:
    reset_sandbox()
    arm_sandbox(limits=_LIMITS, force=True)
    assert sandbox_state() is cp.SandboxState.HEALTHY
    yield
    reset_sandbox()


@pytest.mark.parametrize(
    ("filename", "marker", "doc_kind", "method"),
    [
        pytest.param("memo.txt", "EYENET SMOKE TXT", "text", "text", id="txt-stdlib"),
        pytest.param("page.html", "EYENET SMOKE HTML", "html", "html", id="html-stdlib"),
        pytest.param("note.rtf", "EYENET SMOKE RTF", "rtf", "rtf", id="rtf-stdlib"),
        pytest.param(
            "report.docx",
            "EYENET SMOKE DOCX",
            "zip_ooxml",
            "python-docx",
            id="docx-pandoc",
            marks=_needs_venv,
        ),
        pytest.param(
            "dossier.pdf",
            "EYENET SMOKE",
            "pdf",
            "pymupdf",
            id="pdf-libreoffice",
            marks=_needs_venv,
        ),
    ],
)
def test_smoke_extract_real_file(filename: str, marker: str, doc_kind: str, method: str) -> None:
    blob = (_FIXTURES / filename).read_bytes()
    result = extract_document(blob, limits=_LIMITS)
    assert isinstance(result, ExtractResult), result
    assert marker in result.text
    assert result.meta["doc_kind"] == doc_kind
    assert result.meta["method"] == method
    assert result.meta["empty"] is False


def test_smoke_html_drops_script_and_style() -> None:
    blob = (_FIXTURES / "page.html").read_bytes()
    result = extract_document(blob, limits=_LIMITS)
    assert isinstance(result, ExtractResult)
    assert "EYENET SMOKE HTML" in result.text
    assert "var s=1" not in result.text  # <script> stripped
    assert ".x{}" not in result.text  # <style> stripped


@_needs_venv
@_needs_tess
def test_smoke_ocr_real_scan() -> None:
    blob = (_FIXTURES / "scan.png").read_bytes()
    result = extract_document(blob, limits=_LIMITS)
    assert isinstance(result, ExtractResult), result
    assert "SMOKE" in result.text.upper()
    assert result.meta["ocr_applied"] is True
    assert result.meta["doc_kind"] == "image"
