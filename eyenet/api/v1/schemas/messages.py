# SPDX-License-Identifier: AGPL-3.0-or-later
"""By-id detail schemas for a single message and a single thread.

A message/thread had no by-id read before — they were reachable only inside a
group's message list or an actor's timeline. These are the focused detail
surfaces: one post (author, source, timestamp, body, artifacts, incident labels)
and one thread (its OP post + thread meta). A thread is identified by its
``group_id`` today (threads ride on the group model); ``thread_id`` is that id.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from eyenet.models.infrastructure import InfrastructureArtifactTable
from eyenet.models.message import MessageTable

from ._base import ApiSchema
from .groups import GroupMessage


class ArtifactRef(ApiSchema):
    """One infrastructure artifact mentioned in a message."""

    id: UUID
    kind: str  # open varchar: vendored InfrastructureKind or coded (ipv4/ipv6/...)
    value: str
    first_seen: datetime

    @classmethod
    def from_artifact(cls, a: InfrastructureArtifactTable) -> ArtifactRef:
        return cls(id=a.id, kind=a.kind, value=a.value, first_seen=a.first_seen_at_ingest)


class MessageDetail(ApiSchema):
    """One message in full: the post plus its source and the artifacts found in it."""

    source_id: UUID
    source_display: str | None = None
    group_id: UUID
    message: GroupMessage  # author, ts, body, incident labels, geo — the post itself
    artifacts: list[ArtifactRef] = Field(default_factory=list)

    @classmethod
    def build(
        cls,
        msg: MessageTable,
        message: GroupMessage,
        *,
        source_display: str | None,
        artifacts: list[InfrastructureArtifactTable],
    ) -> MessageDetail:
        return cls(
            source_id=msg.source_id,
            source_display=source_display,
            group_id=msg.group_id,
            message=message,
            artifacts=[ArtifactRef.from_artifact(a) for a in artifacts],
        )


class ThreadDetail(ApiSchema):
    """One thread: its OP post in full, plus thread meta. ``thread_id`` == group_id."""

    thread_id: UUID
    source_id: UUID
    source_display: str | None = None
    title: str | None = None
    post_count: int
    op: MessageDetail
