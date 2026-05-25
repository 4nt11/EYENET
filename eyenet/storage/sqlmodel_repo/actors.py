# SPDX-License-Identifier: AGPL-3.0-or-later
"""ActorsMixin — source / group / actor upsert + actor_key resolve."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import select

from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.models import ActorTable, GroupTable, SourceTable

from ._helpers import safe_session


class ActorsMixin:
    async def resolve_actor_id(self, actor_key: str) -> UUID | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(ActorTable).where(ActorTable.actor_key == actor_key))
            row = result.first()
            return row.id if row else None

    async def upsert_source(
        self,
        *,
        kind: SourceKind,
        display_name: str,
        base_url: str | None = None,
        created_at: datetime,
    ) -> UUID:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(SourceTable).where(
                    SourceTable.kind == kind,
                    SourceTable.display_name == display_name,
                )
            )
            row = result.first()
            if row is None:
                row = SourceTable(
                    kind=kind,
                    display_name=display_name,
                    base_url=base_url,
                    created_at=created_at,
                )
                session.add(row)
                await session.flush()
            row_id = row.id
            await session.commit()
            return row_id

    async def upsert_group(
        self,
        *,
        source_id: UUID,
        platform_groupid: str,
        kind: GroupKind,
        title: str | None,
        seen_at: datetime,
    ) -> UUID:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(GroupTable).where(
                    GroupTable.source_id == source_id,
                    GroupTable.platform_groupid == platform_groupid,
                )
            )
            row = result.first()
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
                await session.flush()
            else:
                row.current_title = title or row.current_title
                stored = row.last_observed_at_ingest
                if stored.tzinfo is None:
                    stored = stored.replace(tzinfo=UTC)
                row.last_observed_at_ingest = max(stored, seen_at)
                session.add(row)
                await session.flush()
            row_id = row.id
            await session.commit()
            return row_id

    async def upsert_actor(
        self,
        *,
        source_id: UUID,
        actor_key: str,
        platform_userid: str,
        handle: str | None,
        display_name: str | None,
        seen_at: datetime,
    ) -> UUID:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(ActorTable).where(ActorTable.actor_key == actor_key))
            row = result.first()
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
                await session.flush()
            else:
                row.current_handle = handle or row.current_handle
                row.current_display_name = display_name or row.current_display_name
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
                await session.flush()
            row_id = row.id
            await session.commit()
            return row_id


__all__ = ["ActorsMixin"]
