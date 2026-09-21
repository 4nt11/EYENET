# SPDX-License-Identifier: AGPL-3.0-or-later
"""Event-log tables — see MODELS.md §2.29 and API_PLAN §11.5.

One row per state-transition event, so the Group H SSE ``StreamReplaySource``
can replay with a per-event delivery span parented from the stored
``traceparent``. Three structurally identical tables; only the parent-id column
name differs. Composite PK ``(<parent>_id, event_seq)`` with ``event_seq``
monotonic per parent. Live in ``main``. The ``eyenet.audit.*`` hash chain serves
this role for audit, so there is no audit event log.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel


class LinkageEventLogTable(SQLModel, table=True):
    __tablename__ = "linkage_event_log"

    linkage_id: UUID = Field(primary_key=True)
    event_seq: int = Field(primary_key=True)
    event_subject: str
    event_id: UUID = Field(index=True)
    ts: datetime = Field(index=True)
    traceparent: str
    tracestate: str | None = None
    actor: str | None = None  # system_user_id for operator actions, null for engine
    payload_digest: str | None = None


class PersonaEventLogTable(SQLModel, table=True):
    __tablename__ = "persona_event_log"

    persona_id: UUID = Field(primary_key=True)
    event_seq: int = Field(primary_key=True)
    event_subject: str
    event_id: UUID = Field(index=True)
    ts: datetime = Field(index=True)
    traceparent: str
    tracestate: str | None = None
    actor: str | None = None
    payload_digest: str | None = None


class IdentityEventLogTable(SQLModel, table=True):
    __tablename__ = "identity_event_log"

    identity_id: UUID = Field(primary_key=True)
    event_seq: int = Field(primary_key=True)
    event_subject: str
    event_id: UUID = Field(index=True)
    ts: datetime = Field(index=True)
    traceparent: str
    tracestate: str | None = None
    actor: str | None = None
    payload_digest: str | None = None


__all__ = [
    "IdentityEventLogTable",
    "LinkageEventLogTable",
    "PersonaEventLogTable",
]
