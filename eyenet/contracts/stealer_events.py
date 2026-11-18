# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stealer-log capture event — drives the ULP processing pipeline.

Emitted by a collector when it stores an attachment blob on a stealer-marked channel
(category=stealer_logs with a storage_uri). The StealerProcessorService subscribes
(queue_group for horizontal fan-out) and runs decrypt → extract → ulpextract →
ClickHouse ingest for the one attachment named here. Carries a POINTER (attachment id),
never payload — the service reads the blob + message body from storage.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from ._base import BusEnvelope

SUBJECT_STEALER_ATTACHMENT_CAPTURED: str = "stealer.attachment.captured"
# Operator-driven reindex of one captured attachment (replay the full
# extract + classify pipeline against a blob that is already stored).
# Also used by the reindex CLI's new API-driven path; the processor's
# handler is the single source of truth for "process this blob".
SUBJECT_STEALER_ATTACHMENT_REINDEX: str = "stealer.attachment.reindex"
# Operator-driven full corpus reindex: processor sweeps every
# attachment via list_stealer_attachments_for_reindex and replays each
# through the pipeline. Scope is admin:stealer at the API layer; the
# bus event itself carries no filter so an eavesdrop cannot narrow it.
SUBJECT_STEALER_CORPUS_REINDEX: str = "stealer.corpus.reindex"
# Operator-driven full corpus reclassify: processor skips extract and
# just re-scores every (archive, victim) pair under the current family
# catalog. Cheap compared to reindex (CH-only).
SUBJECT_STEALER_CORPUS_RECLASSIFY: str = "stealer.corpus.reclassify"


class StealerAttachmentCapturedEnvelope(BusEnvelope):
    """A stealer-log archive blob was captured; process it into creds."""

    attachment_id: UUID = Field(description="PK of the stored stealer attachment")


class StealerAttachmentReindexEnvelope(BusEnvelope):
    """Operator-requested reindex of one stored attachment. The processor
    runs the same pipeline as on initial capture; the StealerProcessing
    row's attempts counter gets bumped so it is visible in the UI."""

    attachment_id: UUID = Field(description="PK of the stored stealer attachment")
    requested_by: UUID | None = Field(
        default=None, description="System user id that requested the reindex"
    )


class StealerCorpusReindexEnvelope(BusEnvelope):
    """Operator-requested full-corpus reindex. The processor sweeps every
    attachment via list_stealer_attachments_for_reindex."""

    requested_by: UUID | None = Field(default=None)
    limit: int = Field(default=0, description="0 == no cap (sweep everything)")


class StealerCorpusReclassifyEnvelope(BusEnvelope):
    """Operator-requested full-corpus reclassify (no extract, just
    re-score verdicts under the current catalog). Cheap compared to
    reindex."""

    requested_by: UUID | None = Field(default=None)


__all__ = [
    "SUBJECT_STEALER_ATTACHMENT_CAPTURED",
    "SUBJECT_STEALER_ATTACHMENT_REINDEX",
    "SUBJECT_STEALER_CORPUS_RECLASSIFY",
    "SUBJECT_STEALER_CORPUS_REINDEX",
    "StealerAttachmentCapturedEnvelope",
    "StealerAttachmentReindexEnvelope",
    "StealerCorpusReclassifyEnvelope",
    "StealerCorpusReindexEnvelope",
]
