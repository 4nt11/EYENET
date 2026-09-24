"""MessageTable + AttachmentTable — see contracts/message.py.

AttachmentTable carries sensitivity columns per API_PLAN §4.7 / §4.9 —
mirrors ObservationTable so reclassification works uniformly across both
evidence-bearing surfaces.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, Index
from sqlmodel import Column, Field, SQLModel

from eyenet.contracts.enums import AttachmentKind, SensitivityTier

from ._base import new_uuid7
from .observation import TIER_MONOTONE_CK


class MessageTable(SQLModel, table=True):
    __tablename__ = "message"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    source_id: UUID = Field(foreign_key="source.id", index=True)
    group_id: UUID = Field(foreign_key="group_.id", index=True)
    actor_id: UUID = Field(foreign_key="actor.id", index=True)
    platform_msgid: str = Field(index=True)
    evidence_ref: str = Field(index=True, unique=True)
    body: str
    body_lang: str | None = None
    length_chars: int
    length_words: int
    sent_at_source: datetime = Field(index=True)
    ingested_at: datetime
    reply_to_msg_id: UUID | None = Field(default=None, foreign_key="message.id")
    forward_of_msg_id: UUID | None = Field(default=None, foreign_key="message.id")
    forward_origin_actor_id: UUID | None = Field(default=None, foreign_key="actor.id")
    has_attachment: bool = False
    source_specific: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    # Copypasta detection (anti-spam §A): set when this body matches a known
    # content template; authorship linkage skips messages whose template is
    # flagged copypasta. NULL = not yet classified / unique text.
    template_id: UUID | None = Field(default=None, foreign_key="content_template.id", index=True)


class ContentTemplateTable(SQLModel, table=True):
    """A repeated message body (copypasta), keyed by its masked fingerprint.

    See ``eyenet.linker.copypasta`` for the fingerprint + ``is_copypasta`` policy
    and ``development/linker-antispam-spec.md`` §2. A template is ``is_copypasta``
    once it is long enough AND posted by enough distinct actors."""

    __tablename__ = "content_template"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    fingerprint: str = Field(unique=True, index=True)
    char_len: int
    occurrence_count: int = 0
    distinct_actor_count: int = 0
    is_copypasta: bool = Field(default=False, index=True)
    sample_body: str
    first_seen_at_ingest: datetime
    last_seen_at_ingest: datetime


class AttachmentTable(SQLModel, table=True):
    __tablename__ = "attachment"
    __table_args__ = (
        Index(
            "ix_attachment_tier",
            "classifier_tier",
            "operator_tier_override",
        ),
        CheckConstraint(TIER_MONOTONE_CK, name="ck_attachment_tier_monotone"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    message_id: UUID = Field(foreign_key="message.id", index=True)
    kind: AttachmentKind
    mime: str
    size_bytes: int
    sha256: str = Field(index=True)
    filename: str | None = None
    storage_uri: str | None = None
    classifier_tier: SensitivityTier = Field(default=SensitivityTier.NORMAL)
    operator_tier_override: SensitivityTier | None = None


__all__ = ["AttachmentTable", "MessageTable"]
