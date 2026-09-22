# SPDX-License-Identifier: AGPL-3.0-or-later
"""`FileAccessJournalRow` contract — a read-side view of one journal row (§5.8).

The exoneration read path returns these instead of leaking ORM rows to the
handler. Field-parity with the columns of
:class:`eyenet.models.file_access.FileAccessJournalTable` that the exoneration
envelope needs. The chain-integrity columns (``prev_journal_hash`` /
``self_hash``) are deliberately omitted: they anchor the tamper-evident chain,
not the per-access disclosure, and the signed ``journal_head_at_query`` already
binds the reader to the chain state.

Surface: db.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from eyenet.contracts.enums import FileServedVia, SensitivityTier


class FileAccessJournalRow(BaseModel):
    """One row of ``file_access_journal`` as seen by the exoneration surface."""

    model_config = ConfigDict(frozen=True)

    access_id: UUID
    audit_event_id: UUID | None
    user_id: UUID
    grant_id: UUID | None
    content_hash: bytes
    content_size: int
    content_mime: str
    tier: SensitivityTier
    served_at: datetime
    served_via: FileServedVia
    signing_pubkey_fingerprint: str


__all__ = ["FileAccessJournalRow"]
