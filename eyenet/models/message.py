"""MessageTable + AttachmentTable — see contracts/message.py."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel

from eyenet.contracts.enums import AttachmentKind

from ._base import new_uuid7


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


class AttachmentTable(SQLModel, table=True):
    __tablename__ = "attachment"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    message_id: UUID = Field(foreign_key="message.id", index=True)
    kind: AttachmentKind
    mime: str
    size_bytes: int
    sha256: str = Field(index=True)
    filename: str | None = None
    storage_uri: str | None = None


__all__ = ["AttachmentTable", "MessageTable"]
