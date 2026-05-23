"""Actor upsert + resolve helpers over messages.db.

Application-side helpers — not an abstract store. The collector writes via
`upsert_actor`; the sensor reads via `resolve_actor_id`. All interactions go
through the messages.db engine (which co-locates actor, source, group_ per
PLAN §5.2 / engines.py `_STORE_TABLES[MESSAGES]`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import Session, select

from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.models import ActorTable, GroupTable, SourceTable


def resolve_actor_id(session: Session, actor_key: str) -> UUID | None:
    """Look up the UUID primary key for an actor_key. None if not yet ingested."""

    row = session.exec(select(ActorTable).where(ActorTable.actor_key == actor_key)).first()
    return row.id if row else None


def upsert_actor(
    session: Session,
    *,
    source_id: UUID,
    actor_key: str,
    platform_userid: str,
    handle: str | None,
    display_name: str | None,
    seen_at: datetime,
) -> UUID:
    """Insert or update an actor row; return its UUID.

    Idempotent on `actor_key` (unique constraint). If the actor exists, updates
    `current_handle`, `current_display_name`, and `last_seen_*` timestamps.
    """

    row = session.exec(select(ActorTable).where(ActorTable.actor_key == actor_key)).first()
    if row is None:
        row = ActorTable(
            actor_key=actor_key,
            source_id=source_id,
            platform_userid=platform_userid,
            current_handle=handle,
            current_display_name=display_name,
            first_seen_at_ingest=seen_at,
            last_seen_at_ingest=seen_at,
            first_seen_at_source=seen_at,
            last_seen_at_source=seen_at,
        )
        session.add(row)
        session.flush()  # populate row.id
    else:
        row.current_handle = handle or row.current_handle
        row.current_display_name = display_name or row.current_display_name
        # SQLite drops tzinfo on round-trip; force UTC-aware comparison.
        li = row.last_seen_at_ingest
        stored_ingest = li if li.tzinfo is not None else li.replace(tzinfo=UTC)
        row.last_seen_at_ingest = max(stored_ingest, seen_at)
        if row.last_seen_at_source is None:
            row.last_seen_at_source = seen_at
        else:
            ls = row.last_seen_at_source
            stored_src = ls if ls.tzinfo is not None else ls.replace(tzinfo=UTC)
            if seen_at > stored_src:
                row.last_seen_at_source = seen_at
        session.add(row)
        session.flush()
    return row.id


def upsert_source(
    session: Session,
    *,
    kind: SourceKind,
    display_name: str,
    base_url: str | None = None,
    created_at: datetime,
) -> UUID:
    """Find or create a SourceTable row for this (kind, display_name) pair."""

    row = session.exec(
        select(SourceTable).where(
            SourceTable.kind == kind,
            SourceTable.display_name == display_name,
        )
    ).first()
    if row is None:
        row = SourceTable(
            kind=kind,
            display_name=display_name,
            base_url=base_url,
            created_at=created_at,
        )
        session.add(row)
        session.flush()
    return row.id


def upsert_group(
    session: Session,
    *,
    source_id: UUID,
    platform_groupid: str,
    kind: GroupKind,
    title: str | None,
    seen_at: datetime,
) -> UUID:
    """Find or create a GroupTable row."""

    row = session.exec(
        select(GroupTable).where(
            GroupTable.source_id == source_id,
            GroupTable.platform_groupid == platform_groupid,
        )
    ).first()
    if row is None:
        row = GroupTable(
            source_id=source_id,
            platform_groupid=platform_groupid,
            kind=kind,
            current_title=title,
            first_seen_at_ingest=seen_at,
            last_observed_at_ingest=seen_at,
        )
        session.add(row)
        session.flush()
    else:
        row.current_title = title or row.current_title
        stored = row.last_observed_at_ingest
        if stored.tzinfo is None:
            stored = stored.replace(tzinfo=UTC)
        row.last_observed_at_ingest = max(stored, seen_at)
        session.add(row)
        session.flush()
    return row.id


__all__ = ["resolve_actor_id", "upsert_actor", "upsert_group", "upsert_source"]
