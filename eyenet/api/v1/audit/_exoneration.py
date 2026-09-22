# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared mapping for the file-access exoneration handlers (§5.8)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from eyenet.api.v1.schemas.attachments import FileAccessJournalEntry

if TYPE_CHECKING:
    from eyenet.contracts.file_access import FileAccessJournalRow


def journal_entry(row: FileAccessJournalRow) -> FileAccessJournalEntry:
    """Map a stored journal row to its wire entry.

    ``operator_signature_verified`` is True by construction: ``record_access``
    verifies the operator signature BEFORE writing a row and fails closed
    otherwise, so any persisted row was verified when it was written.
    """
    return FileAccessJournalEntry(
        access_id=row.access_id,
        audit_event_id=row.audit_event_id,
        user_id=row.user_id,
        grant_id=row.grant_id,
        content_hash=row.content_hash.hex(),
        content_size=row.content_size,
        content_mime=row.content_mime,
        tier=row.tier,
        served_at=row.served_at,
        served_via=row.served_via,
        operator_signature_verified=True,
        signing_pubkey_fingerprint=row.signing_pubkey_fingerprint,
    )


__all__ = ["journal_entry"]
