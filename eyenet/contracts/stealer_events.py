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
# Jump-the-line per-attachment reindex. Same envelope as
# SUBJECT_STEALER_ATTACHMENT_REINDEX; the processor serves it off a
# dedicated subscription (queue_group="stealer_urgent") so it never
# queues behind an in-flight corpus sweep. Use for "this one blob, now."
SUBJECT_STEALER_ATTACHMENT_REINDEX_URGENT: str = "stealer.attachment.reindex.urgent"
# Operator-driven full corpus reclassify: processor skips extract and
# just re-scores every (archive, victim) pair under the current family
# catalog. Cheap compared to reindex (CH-only).
SUBJECT_STEALER_CORPUS_RECLASSIFY: str = "stealer.corpus.reclassify"
# Reindex-by-RULE: re-extract only specific rule_ids across the corpus without
# re-running the whole catalog. The processor per-member-extracts just the files
# matching each rule's path_glob and runs gotractor with the rule subset. Cheap
# way to backfill a newly-added or newly-fixed rule (e.g. the json_v2 pc_info.json
# fingerprint lane) without a full re-extract. See
# development/PCINFO_JSON_GAP_AND_REINDEX_BY_RULE_SCOPE.md.
SUBJECT_STEALER_RULE_REINDEX: str = "stealer.rule.reindex"


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
    resume: bool = Field(
        default=False,
        description="Resume an interrupted sweep: skip attachments already "
        "STEALER_DONE (the per-attachment state is the cursor) and process only "
        "not-done ones. Default False = full replay, force-reprocess every "
        "attachment (correct for a from-zero rebuild). Resume continues an "
        "interrupted run; it does NOT apply a changed ruleset -- use a full "
        "replay (or stealer-reclassify) for that.",
    )


class StealerCorpusReclassifyEnvelope(BusEnvelope):
    """Operator-requested full-corpus reclassify (no extract, just
    re-score verdicts under the current catalog). Cheap compared to
    reindex."""

    requested_by: UUID | None = Field(default=None)


class StealerRuleReindexEnvelope(BusEnvelope):
    """Operator-requested reindex of specific RULE ids across the corpus. The
    processor walks attachments (resume-aware), and per attachment lists the
    archive, keeps only members matching the target rules' path_globs,
    per-member-extracts those, and runs gotractor with the rule subset. Only the
    target rules' rows are (re)emitted; ReplacingMergeTree dedups, other rules'
    rows are untouched. Re-decrypts per archive but skips the whole-catalog walk
    + heavy-rule re-insert. For a newly added/fixed rule, not a from-zero rebuild."""

    rule_ids: list[str] = Field(description="Content rule ids to (re)extract")
    requested_by: UUID | None = Field(default=None)
    limit: int = Field(default=0, description="0 == no cap (sweep everything)")
    resume: bool = Field(
        default=False,
        description="Skip attachments already done for THIS rule set (cursor keyed "
        "on the rule reindex). Default False = sweep all archives that have "
        "matching members.",
    )


__all__ = [
    "SUBJECT_STEALER_ATTACHMENT_CAPTURED",
    "SUBJECT_STEALER_ATTACHMENT_REINDEX",
    "SUBJECT_STEALER_ATTACHMENT_REINDEX_URGENT",
    "SUBJECT_STEALER_CORPUS_RECLASSIFY",
    "SUBJECT_STEALER_CORPUS_REINDEX",
    "SUBJECT_STEALER_RULE_REINDEX",
    "StealerAttachmentCapturedEnvelope",
    "StealerAttachmentReindexEnvelope",
    "StealerCorpusReclassifyEnvelope",
    "StealerCorpusReindexEnvelope",
    "StealerRuleReindexEnvelope",
]  # grouped by subject constants then envelopes
