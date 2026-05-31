"""Classifier orchestration — the reusable core behind every entry point.

CLASSIFIER_PLAN §4/§5. The deterministic pipeline (extract→regex→presidio→
aggregate→advise) lives once in :func:`classify_blob`; three thin orchestrators
wrap it for the three entry points:

    classify_blob   →  pure pipeline: bytes → settled verdict + text + meta
                       (no storage, no audit — unit-testable with fakes)

    ingest_document →  SYNC CLI path (`eyenet document ingest`): store bytes +
                       classify + persist the SETTLED DocumentRow + audit.

    stage_document  →  async upload entry: store bytes + persist a PROVISIONAL
       + settle_document  CLASSIFIED row; the ClassifierService later reads the
                       bytes back, classifies, and settles the tier.

    classify_attachment → async collector entry: read a stored attachment's
                       bytes, classify, stamp AttachmentTable.classifier_tier.

§0 binds throughout: a `FailedClosed` extraction (or any presidio fail-closed)
settles at CLASSIFIED via :func:`aggregate`; the LLM is flag-only (tier never
moves). The sync nsjail calls (`extract_document`, `detect`) run on a worker
thread so the async paths never block their event loop; `advise` is async +
fail-soft.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from eyenet.classifier.aggregate import (
    aggregate,
    apply_llm_advisory,
    classification_audit_payload,
)
from eyenet.classifier.extract import extract_document
from eyenet.classifier.llm import advise, sanitize_model_text
from eyenet.classifier.presidio import detect
from eyenet.classifier.ruleset import classify, load_ruleset
from eyenet.classifier.sandbox import ExtractResult
from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.document import DocumentRow
from eyenet.contracts.enums import SensitivityTier
from eyenet.storage.documents import store_document

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from eyenet.classifier.aggregate import ClassificationVerdict
    from eyenet.classifier.llm import LlmAdvisory, LlmUnavailable
    from eyenet.storage.repository import BaseRepository
    from eyenet.telemetry.audit import AuditEmitter

    AdviseFn = Callable[[str], Awaitable[LlmAdvisory | LlmUnavailable]]

__all__ = [
    "ClassifiedDoc",
    "IngestResult",
    "classify_attachment",
    "classify_blob",
    "ingest_document",
    "settle_document",
    "stage_document",
]

_log = structlog.get_logger()

# Caps for sanitized embedded-metadata strings (a hostile XMP packet can be
# large; keys are short identifiers).
_META_STR_CAP = 4096
_META_KEY_CAP = 128

_DEFAULT_MIME = "application/octet-stream"


@dataclass(frozen=True, slots=True)
class ClassifiedDoc:
    """The deterministic outcome of running the pipeline over one blob."""

    verdict: ClassificationVerdict
    text: str
    embedded_meta: dict[str, object]
    doc_kind: str | None


@dataclass(frozen=True, slots=True)
class IngestResult:
    """The outcome of one document ingest — persisted id + the settled verdict."""

    document_id: UUID
    sha256: str
    verdict: ClassificationVerdict


def _sani_value(value: object) -> object:
    """Recursively neutralize an embedded-metadata value (untrusted, §slice-6)."""
    if isinstance(value, str):
        return sanitize_model_text(value, max_len=_META_STR_CAP)
    if isinstance(value, dict):
        return {_sani_key(key): _sani_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sani_value(item) for item in value]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return sanitize_model_text(str(value), max_len=_META_STR_CAP)


def _sani_key(key: object) -> str:
    return sanitize_model_text(str(key), max_len=_META_KEY_CAP)


def _sanitize_meta(meta: dict[str, object]) -> dict[str, object]:
    """Sanitize every key/value in the extraction meta before it is stored.

    Embedded document metadata is attacker-controlled (it is what the document
    *claims* about itself), so it is HTML-escaped / control-stripped here — the
    same boundary the slice-6 LLM output crosses. Captured verbatim as evidence,
    rendered inert.
    """
    return {_sani_key(key): _sani_value(value) for key, value in meta.items()}


def _meta_text(meta: dict[str, object]) -> str:
    """Flatten sanitized embedded metadata into one newline-joined string.

    Slice 9: the ruleset runs over this as a second text source so a
    classification banner hidden in XMP keywords / DOCX core-props escalates the
    tier (escalate-only, §0). Walks keys + string leaves of the (already
    sanitized) meta dict; numbers/bools/None carry no markings and are skipped.
    """
    parts: list[str] = []

    def _walk(value: object) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                parts.append(str(key))
                _walk(item)
        elif isinstance(value, list):
            for item in value:
                _walk(item)

    _walk(meta)
    return "\n".join(parts)


async def classify_blob(blob: bytes, *, advise_fn: AdviseFn | None = None) -> ClassifiedDoc:
    """Run the full deterministic pipeline over raw bytes; no I/O side effects.

    Returns the settled verdict + extracted text + sanitized embedded metadata.
    The §0 floors bind here (unreadable → CLASSIFIED); the LLM only flags.
    """
    extraction = await asyncio.to_thread(extract_document, blob)
    raw_meta = extraction.meta if isinstance(extraction, ExtractResult) else {}
    text = extraction.text if isinstance(extraction, ExtractResult) else ""
    sanitized_meta = _sanitize_meta(raw_meta)

    ruleset = load_ruleset()
    regex = classify(text, ruleset)
    # Escalate-only metadata floor (slice 9): the SAME ruleset over the sanitized
    # embedded metadata catches a banner hidden in XMP/core-props on an
    # empty-body doc. Runs even when `text` is empty (the gap we are closing).
    meta_regex = classify(_meta_text(sanitized_meta), ruleset)
    presidio = await asyncio.to_thread(detect, text)
    verdict = aggregate(extraction, regex, presidio, meta_regex=meta_regex)
    if verdict.consult_llm:
        # Resolved at call time (not a bound default) so a test/operator can
        # swap the provider via the module global without a network round-trip.
        resolved_advise = advise_fn or advise
        verdict = apply_llm_advisory(verdict, await resolved_advise(text))

    doc_kind = raw_meta.get("doc_kind")
    return ClassifiedDoc(
        verdict=verdict,
        text=text,
        embedded_meta=sanitized_meta,
        doc_kind=str(doc_kind) if doc_kind is not None else None,
    )


async def ingest_document(
    blob: bytes,
    *,
    storage: BaseRepository,
    data_dir: Path,
    audit: AuditEmitter | None = None,
    uploaded_by: UUID | None = None,
    filename: str | None = None,
    mime: str | None = None,
    now: datetime | None = None,
    advise_fn: AdviseFn | None = None,
) -> IngestResult:
    """Classify + persist one document SYNCHRONOUSLY (the CLI path).

    The byte store + sha256 are host-side (custody); the tier is the BINDING
    ``MAX`` of the deterministic floors and is never lowered by the advisory
    LLM. The async upload path uses :func:`stage_document` + :func:`settle_document`
    instead; this single-shot variant stays for the operator-blocking CLI.
    """
    at = now or datetime.now(tz=UTC)
    sha256, storage_uri = store_document(data_dir, blob)

    classified = await classify_blob(blob, advise_fn=advise_fn)
    verdict = classified.verdict

    row = DocumentRow(
        sha256=sha256,
        mime=mime or _DEFAULT_MIME,
        size_bytes=len(blob),
        doc_kind=classified.doc_kind,
        filename=filename,
        storage_uri=storage_uri,
        extracted_text=classified.text or None,
        embedded_meta=classified.embedded_meta,
        classification=classification_audit_payload(verdict),
        review_required=bool(verdict.review_flags),
        uploaded_by_user_id=uploaded_by,
        uploaded_at=at,
        ingested_at=at,
        classifier_tier=verdict.tier,
    )
    document_id = await storage.put_document(row)
    _log.info(
        "classify.document_ingested",
        document_id=str(document_id),
        tier=verdict.tier.value,
        doc_kind=row.doc_kind,
        review_required=row.review_required,
        fail_closed=verdict.fail_closed,
    )

    if audit is not None:
        await _emit_audit(
            audit,
            subject_kind="document",
            subject_id=document_id,
            system_user_id=uploaded_by,
            verdict=verdict,
        )

    return IngestResult(document_id=document_id, sha256=sha256, verdict=verdict)


async def stage_document(
    blob: bytes,
    *,
    storage: BaseRepository,
    data_dir: Path,
    uploaded_by: UUID | None = None,
    filename: str | None = None,
    mime: str | None = None,
    now: datetime | None = None,
) -> tuple[UUID, str]:
    """Store bytes + persist a PROVISIONAL CLASSIFIED row; return (id, sha256).

    The fast, non-blocking half of the async upload path: NO extraction happens
    here. The row is born CLASSIFIED (§0 fail-closed — nothing below clearance
    is served before :func:`settle_document` runs). The caller then publishes a
    ``classify.document.uploaded`` event for the ClassifierService to settle.
    """
    at = now or datetime.now(tz=UTC)
    sha256, storage_uri = store_document(data_dir, blob)

    row = DocumentRow(
        sha256=sha256,
        mime=mime or _DEFAULT_MIME,
        size_bytes=len(blob),
        doc_kind=None,
        filename=filename,
        storage_uri=storage_uri,
        extracted_text=None,
        embedded_meta={},
        classification={},
        review_required=False,
        uploaded_by_user_id=uploaded_by,
        uploaded_at=at,
        ingested_at=at,
        classifier_tier=SensitivityTier.CLASSIFIED,
    )
    document_id = await storage.put_document(row)
    _log.info("classify.document_staged", document_id=str(document_id), sha256=sha256)
    return document_id, sha256


async def settle_document(
    document_id: UUID,
    *,
    storage: BaseRepository,
    audit: AuditEmitter | None = None,
    advise_fn: AdviseFn | None = None,
    now: datetime | None = None,
) -> ClassificationVerdict:
    """Read a staged document's bytes, classify, and settle its tier (async path).

    Idempotent on bus re-delivery — the verdict is deterministic, so re-settling
    overwrites the same values. A failure raises (the row stays provisional
    CLASSIFIED — fail-closed, re-drivable).
    """
    at = now or datetime.now(tz=UTC)
    row = await storage.get_document(document_id)
    if row is None:
        raise ValueError(f"document {document_id} not found")
    if row.storage_uri is None:
        raise RuntimeError(f"document {document_id} has no storage_uri to read bytes from")

    blob = await asyncio.to_thread(Path(row.storage_uri).read_bytes)
    classified = await classify_blob(blob, advise_fn=advise_fn)
    verdict = classified.verdict

    await storage.settle_document_classification(
        document_id,
        tier=verdict.tier,
        doc_kind=classified.doc_kind,
        extracted_text=classified.text or None,
        embedded_meta=classified.embedded_meta,
        classification=classification_audit_payload(verdict),
        review_required=bool(verdict.review_flags),
        ingested_at=at,
    )
    _log.info(
        "classify.document_settled",
        document_id=str(document_id),
        tier=verdict.tier.value,
        doc_kind=classified.doc_kind,
        review_required=bool(verdict.review_flags),
        fail_closed=verdict.fail_closed,
    )

    if audit is not None:
        await _emit_audit(
            audit,
            subject_kind="document",
            subject_id=document_id,
            system_user_id=row.uploaded_by_user_id,
            verdict=verdict,
        )
    return verdict


async def classify_attachment(
    attachment_id: UUID,
    *,
    storage: BaseRepository,
    audit: AuditEmitter | None = None,
    advise_fn: AdviseFn | None = None,
) -> ClassificationVerdict:
    """Read a stored attachment's bytes, classify, and stamp its tier (async path).

    The collector created the AttachmentTable row (provisional CLASSIFIED) and
    published ``classify.attachment.stored``. Idempotent on re-delivery.
    """
    row = await storage.get_attachment(attachment_id)
    if row is None:
        raise ValueError(f"attachment {attachment_id} not found")
    if row.storage_uri is None:
        raise RuntimeError(f"attachment {attachment_id} has no storage_uri to read bytes from")

    blob = await asyncio.to_thread(Path(row.storage_uri).read_bytes)
    classified = await classify_blob(blob, advise_fn=advise_fn)
    verdict = classified.verdict

    await storage.set_attachment_classification(attachment_id, verdict.tier)
    _log.info(
        "classify.attachment_settled",
        attachment_id=str(attachment_id),
        tier=verdict.tier.value,
        doc_kind=classified.doc_kind,
        review_required=bool(verdict.review_flags),
        fail_closed=verdict.fail_closed,
    )

    if audit is not None:
        await _emit_audit(
            audit,
            subject_kind="attachment",
            subject_id=attachment_id,
            system_user_id=None,
            verdict=verdict,
        )
    return verdict


async def _emit_audit(
    audit: AuditEmitter,
    *,
    subject_kind: str,
    subject_id: UUID,
    system_user_id: UUID | None,
    verdict: ClassificationVerdict,
) -> None:
    """Record the settled classification (+ a review-flag row when flagged).

    Payload is the redacted ``classification_audit_payload`` — never raw spans,
    never the LLM's free-text summary (clearance-gated, dropped by ``redacted``).
    """
    payload = classification_audit_payload(verdict)
    evidence_ref = f"{subject_kind}:{subject_id}"
    await audit.emit(
        event=AuditSubject.CLASSIFY_AGGREGATED,
        subject_kind=subject_kind,
        subject_id=subject_id,
        evidence_ref=evidence_ref,
        system_user_id=system_user_id,
        payload=payload,
    )
    if verdict.review_flags:
        await audit.emit(
            event=AuditSubject.CLASSIFY_REVIEW_FLAGGED,
            subject_kind=subject_kind,
            subject_id=subject_id,
            evidence_ref=evidence_ref,
            system_user_id=system_user_id,
            payload=payload,
        )
