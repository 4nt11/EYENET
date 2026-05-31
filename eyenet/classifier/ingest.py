"""Ingest one document end-to-end: store → extract → classify → persist → audit.

This is the reusable orchestration core of the M10 classifier (CLASSIFIER_PLAN
§4). The upload endpoint and the ``eyenet document ingest`` CLI both call it; the
slice-8 ``ClassifierService`` is *only the bus/service harness* that wraps it.

It runs the FULL deterministic chain synchronously and persists the SETTLED
tier:

    store_document  → host-side sha256 (custody) + on-disk bytes
    extract_document→ jailed text + embedded metadata (sanitized host-side)
    classify        → regex floor          ┐
    detect          → presidio floor        ├─ aggregate → MAX (BINDING) tier
    extraction floor                        ┘
    advise (if < CLASSIFIED) → flag-only LLM advisory (tier never moves, §0/§4)

``extract_document`` and ``detect`` are SYNC subprocess/nsjail calls, so they run
in a worker thread (``anyio.to_thread.run_sync``) to keep the event loop free;
``advise`` is async and fail-soft. Any unhandled error propagates — the caller
fails the request / exits non-zero rather than persist a half-classified row.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
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
from eyenet.storage.documents import store_document

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path
    from uuid import UUID

    from eyenet.classifier.aggregate import ClassificationVerdict
    from eyenet.classifier.llm import LlmAdvisory, LlmUnavailable
    from eyenet.storage.repository import BaseRepository
    from eyenet.telemetry.audit import AuditEmitter

    AdviseFn = Callable[[str], Awaitable[LlmAdvisory | LlmUnavailable]]

__all__ = ["IngestResult", "ingest_document"]

_log = structlog.get_logger()

# Caps for sanitized embedded-metadata strings (a hostile XMP packet can be
# large; keys are short identifiers).
_META_STR_CAP = 4096
_META_KEY_CAP = 128

_DEFAULT_MIME = "application/octet-stream"


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
    """Classify + persist one uploaded document, returning the settled verdict.

    The byte store + sha256 are host-side (custody); extraction + PII detection
    run jailed; the tier is the BINDING ``MAX`` of the deterministic floors and
    is never lowered by the advisory LLM. ``audit`` (when supplied) records the
    classification decision; the slice-8 service injects its own emitter.
    """
    at = now or datetime.now(tz=UTC)
    sha256, storage_uri = store_document(data_dir, blob)

    extraction = await asyncio.to_thread(extract_document, blob)
    raw_meta = extraction.meta if isinstance(extraction, ExtractResult) else {}
    text = extraction.text if isinstance(extraction, ExtractResult) else ""

    regex = classify(text, load_ruleset())
    presidio = await asyncio.to_thread(detect, text)
    verdict = aggregate(extraction, regex, presidio)
    if verdict.consult_llm:
        # Resolved at call time (not a bound default) so a test/operator can
        # swap the provider via the module global without a network round-trip.
        resolved_advise = advise_fn or advise
        verdict = apply_llm_advisory(verdict, await resolved_advise(text))

    doc_kind = raw_meta.get("doc_kind")
    row = DocumentRow(
        sha256=sha256,
        mime=mime or _DEFAULT_MIME,
        size_bytes=len(blob),
        doc_kind=str(doc_kind) if doc_kind is not None else None,
        filename=filename,
        storage_uri=storage_uri,
        extracted_text=text or None,
        embedded_meta=_sanitize_meta(raw_meta),
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
        await _emit_audit(audit, document_id, uploaded_by, verdict)

    return IngestResult(document_id=document_id, sha256=sha256, verdict=verdict)


async def _emit_audit(
    audit: AuditEmitter,
    document_id: UUID,
    uploaded_by: UUID | None,
    verdict: ClassificationVerdict,
) -> None:
    """Record the settled classification (+ a review-flag row when flagged).

    Payload is the redacted ``classification_audit_payload`` — never raw spans,
    never the LLM's free-text summary (clearance-gated, dropped by ``redacted``).
    """
    payload = classification_audit_payload(verdict)
    evidence_ref = f"document:{document_id}"
    await audit.emit(
        event=AuditSubject.CLASSIFY_AGGREGATED,
        subject_kind="document",
        subject_id=document_id,
        evidence_ref=evidence_ref,
        system_user_id=uploaded_by,
        payload=payload,
    )
    if verdict.review_flags:
        await audit.emit(
            event=AuditSubject.CLASSIFY_REVIEW_FLAGGED,
            subject_kind="document",
            subject_id=document_id,
            evidence_ref=evidence_ref,
            system_user_id=uploaded_by,
            payload=payload,
        )
