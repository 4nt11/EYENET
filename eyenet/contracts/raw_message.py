"""`RawMessage` bus envelope + persisted row (MODELS §1.4, PLAN §3, §4.3).

PLAN §4.3 mandates: bus envelope carries hashes/aggregates and an
`evidence_ref` only — bodies stay in `MessageStore`. Subscribers dereference
`evidence_ref` and that dereference is audited (`eyenet.audit.evidence_access`).

Subject: `raw.message.{source}.{instance_id}`.
Surface: bus+db.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from ._base import BusEnvelope
from .enums import SourceKind

SUBJECT: str = "raw.message.{source}.{instance_id}"


def subject_for(source: SourceKind | str, instance_id: str) -> str:
    """Render the bus subject for a (source, collector instance_id) pair."""

    kind = source.value if isinstance(source, SourceKind) else source
    return f"raw.message.{kind}.{instance_id}"


class RawMessageEnvelope(BusEnvelope):
    """Raw-message bus envelope. References the body via `evidence_ref` only."""

    source: SourceKind
    instance_id: str = Field(min_length=8, max_length=8, description="collector instance_id")
    evidence_ref: str = Field(description="dereferenceable handle into MessageStore")
    actor_key: str = Field(description="opaque actor join key (PLAN §0)")
    platform_groupid: str
    platform_msgid: str
    sent_at_source: datetime
    collected_at: datetime
    length_chars: int
    length_words: int
    body_sha256: str = Field(min_length=64, max_length=64)
    is_forward: bool = False
    has_attachment: bool = False
    reply_to_platform_msgid: str | None = None


__all__ = ["SUBJECT", "RawMessageEnvelope", "subject_for"]
