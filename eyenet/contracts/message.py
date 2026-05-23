"""`Message` and `Attachment` contracts (MODELS §1.4, §2.9).

`MessageRow` is db-only — bus side rides `RawMessageEnvelope` (raw_message.py).
Bodies stay server-side per PLAN §4.3.

Surface: db.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from ._base import DbRowBase
from .enums import AttachmentKind


class MessageRow(DbRowBase):
    """Persisted message — full body retained server-side (MODELS §1.4)."""

    source_id: UUID
    group_id: UUID
    actor_id: UUID
    platform_msgid: str
    evidence_ref: str = Field(description="canonical handle, e.g. telegram:<chat>:<msg>")
    body: str
    body_lang: str | None = None
    length_chars: int
    length_words: int
    sent_at_source: datetime
    ingested_at: datetime
    reply_to_msg_id: UUID | None = None
    forward_of_msg_id: UUID | None = None
    forward_origin_actor_id: UUID | None = None
    has_attachment: bool = False
    source_specific: dict[str, object] = Field(default_factory=dict)


class AttachmentRow(DbRowBase):
    """Attachment metadata, NOT the binary (MODELS §2.9, PLAN §5.1).

    Per-Case opt-in flips download retention on; until then `storage_uri=None`.
    """

    message_id: UUID
    kind: AttachmentKind
    mime: str
    size_bytes: int
    sha256: str
    filename: str | None = None
    storage_uri: str | None = None


__all__ = ["AttachmentRow", "MessageRow"]
