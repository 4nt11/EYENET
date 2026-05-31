"""Classifier ingest trigger envelopes (M10 slice 8, PLAN §3, §5).

The document classifier runs as an async worker (`ClassifierService`). Evidence
arrives at a fast, non-blocking entry point that stores the bytes and persists a
**provisional CLASSIFIED** row (fail-closed by construction — nothing below
clearance is served before the pipeline settles), then publishes one of these
events. The service dereferences the pointer, reads the bytes server-side, runs
the deterministic pipeline, and settles the authoritative `classifier_tier`.

Like every EYENET bus message (PLAN §4.3) these carry a *pointer*, never the
payload: the binary stays server-side on disk, referenced by id / `storage_uri`.

Subjects: `classify.document.uploaded`, `classify.attachment.stored`.
Surface: bus.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from ._base import BusEnvelope

SUBJECT_DOCUMENT_UPLOADED: str = "classify.document.uploaded"
SUBJECT_ATTACHMENT_STORED: str = "classify.attachment.stored"


class DocumentUploadedEnvelope(BusEnvelope):
    """A standalone upload was staged; classify + settle its provisional row."""

    document_id: UUID = Field(description="DocumentTable PK of the staged provisional row")


class AttachmentStoredEnvelope(BusEnvelope):
    """A collector stored an attachment; classify + stamp its classifier_tier."""

    attachment_id: UUID = Field(description="AttachmentTable PK")
    message_id: UUID = Field(description="parent MessageTable PK")
    storage_uri: str = Field(description="absolute on-disk path to the attachment bytes")
    sha256: str = Field(min_length=64, max_length=64)
    mime: str


__all__ = [
    "SUBJECT_ATTACHMENT_STORED",
    "SUBJECT_DOCUMENT_UPLOADED",
    "AttachmentStoredEnvelope",
    "DocumentUploadedEnvelope",
]
