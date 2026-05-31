"""Document extraction — Stage 0 of the classifier pipeline.

``extract_document(blob)`` is the single entry the rest of the pipeline calls. It
sniffs the file type from leading bytes (never the extension), routes the blob to
the right jailed parser through the Slice-1 chokepoint, and returns a normalized
:class:`ExtractResult` or a reasoned :class:`FailedClosed`.

Every parser runs behind ``extract_sandboxed`` — EYENET never imports a document
parser into its own address space. Adapters here only choose *which* worker and
*which* least-privilege profile; the security boundary is the sandbox.

Failure is always closed: an unroutable blob, a missing extractor, a crash, a
kill, a timeout, or garbage output all yield :class:`FailedClosed`, which the
aggregator (a later slice) binds to the highest sensitivity tier. Extraction
itself only reports facts and flags (``empty``, ``ocr_applied``, ``doc_kind``);
it does not decide tiers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from eyenet.classifier.sandbox import (
    DEFAULT_LIMITS,
    ExtractResult,
    FailedClosed,
    FailReason,
    extract_sandboxed,
    stdlib_profile,
    tesseract_profile,
    venv_profile,
)

from ._sniff import DocKind, sniff

if TYPE_CHECKING:
    from typing import Literal

    from eyenet.classifier.sandbox import SandboxLimits, SandboxProfile

__all__ = ["DocKind", "extract_document"]

_log = structlog.get_logger()

_WORKER_DIR = Path(__file__).parent / "_workers"

# The second IMAGE pass — Pillow EXIF, run as a venv Python worker alongside the
# Tesseract OCR entrypoint (the two can't share a process: the jail KILLs fork).
_IMAGE_META_WORKER = "image_meta_worker.py"


@dataclass(frozen=True, slots=True)
class _Route:
    """How one document kind is extracted: worker script + output interpretation."""

    worker: str | None  # worker script name, or None for a non-Python entrypoint
    interpret: Literal["envelope", "raw_text"]


# The routing table. Images have no Python worker — Tesseract is its own jail
# entrypoint and its raw stdout IS the OCR text. Everything else runs a worker
# whose stdout is the {"text","meta"} envelope.
_ROUTES: dict[DocKind, _Route] = {
    DocKind.PDF: _Route("pdf_worker.py", "envelope"),
    DocKind.ZIP_OOXML: _Route("docx_worker.py", "envelope"),
    DocKind.TEXT: _Route("text_worker.py", "envelope"),
    DocKind.RTF: _Route("rtf_worker.py", "envelope"),
    DocKind.HTML: _Route("html_worker.py", "envelope"),
    DocKind.IMAGE: _Route(None, "raw_text"),
}


def _build_profile(kind: DocKind) -> SandboxProfile | None:
    """Select the least-privilege profile for a kind (None => extractor missing).

    PDF/DOCX use the venv profile (parser libs on PYTHONPATH); images use the
    Tesseract entrypoint; everything else is the stdlib base. All profiles share
    the one base allowlist and run single-threaded. Builders are resolved at call
    time so a host lacking the venv or Tesseract degrades that kind cleanly.
    """
    if kind in (DocKind.PDF, DocKind.ZIP_OOXML):
        return venv_profile()
    if kind is DocKind.IMAGE:
        return tesseract_profile()
    return stdlib_profile()


def _normalize(result: ExtractResult, kind: DocKind) -> ExtractResult:
    """Stamp uniform provenance/flags onto the worker's result for downstream use."""
    meta = dict(result.meta)
    meta.setdefault("doc_kind", kind.value)
    meta["ocr_applied"] = kind is DocKind.IMAGE
    meta["empty"] = not result.text.strip()
    return ExtractResult(text=result.text, meta=meta)


def _extract_image_exif(blob: bytes, limits: SandboxLimits) -> dict[str, object]:
    """Best-effort EXIF pass for an image (second jailed run, Pillow worker).

    Returns the EXIF dict, or ``{}`` if the venv is absent or the pass fails.
    EXIF is supplementary evidence: its absence must NOT fail-close a document
    whose OCR text we read successfully (§0 is about unreadable CONTENT, not
    missing metadata).
    """
    profile = venv_profile()
    if profile is None:
        _log.warning("extract.image_meta_unavailable", reason="venv_missing")
        return {}
    result = extract_sandboxed(
        blob,
        worker_path=str(_WORKER_DIR / _IMAGE_META_WORKER),
        limits=limits,
        profile=profile,
        interpret="envelope",
    )
    if isinstance(result, FailedClosed):
        _log.warning(
            "extract.image_meta_failed", reason=result.reason.value, detail=result.detail[:200]
        )
        return {}
    exif = result.meta.get("exif", {})
    return exif if isinstance(exif, dict) else {}


def _extract_image(blob: bytes, limits: SandboxLimits) -> ExtractResult | FailedClosed:
    """IMAGE two-pass: Tesseract OCR (text) + Pillow EXIF (metadata), merged.

    The OCR pass is authoritative for §0 — if we can't OCR the image we can't
    read its content, so a failed OCR pass fails the document closed. The EXIF
    pass is best-effort and runs regardless of whether OCR produced any text.
    """
    profile = _build_profile(DocKind.IMAGE)
    if profile is None:
        _log.error("extract.extractor_unavailable", kind=DocKind.IMAGE.value)
        return FailedClosed(
            reason=FailReason.EXTRACTOR_UNAVAILABLE,
            detail="tesseract is not installed on this host",
        )
    ocr = extract_sandboxed(
        blob, worker_path=None, limits=limits, profile=profile, interpret="raw_text"
    )
    if isinstance(ocr, FailedClosed):
        return ocr
    meta = dict(ocr.meta)
    meta["exif"] = _extract_image_exif(blob, limits)
    return _normalize(ExtractResult(text=ocr.text, meta=meta), DocKind.IMAGE)


def extract_document(
    blob: bytes, *, limits: SandboxLimits = DEFAULT_LIMITS
) -> ExtractResult | FailedClosed:
    """Sniff, route, and extract one untrusted document through the sandbox."""
    kind = sniff(blob)
    if kind is DocKind.IMAGE:  # two-pass (OCR + EXIF) — see _extract_image
        return _extract_image(blob, limits)

    route = _ROUTES.get(kind)
    if route is None:  # DocKind.UNKNOWN — nothing claimed it
        _log.info("extract.unsupported_type", kind=kind.value)
        return FailedClosed(
            reason=FailReason.UNSUPPORTED_TYPE,
            detail=f"no parser routes blob of kind={kind.value}",
        )

    profile = _build_profile(kind)
    if profile is None:
        _log.error("extract.extractor_unavailable", kind=kind.value)
        return FailedClosed(
            reason=FailReason.EXTRACTOR_UNAVAILABLE,
            detail=f"extractor for kind={kind.value} is not installed on this host",
        )

    worker_path = str(_WORKER_DIR / route.worker) if route.worker is not None else None
    result = extract_sandboxed(
        blob,
        worker_path=worker_path,
        limits=limits,
        profile=profile,
        interpret=route.interpret,
    )
    if isinstance(result, FailedClosed):
        return result
    return _normalize(result, kind)
