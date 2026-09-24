# SPDX-License-Identifier: AGPL-3.0-or-later
"""RelationsMixin — actor-to-actor relationship (mention/forward) store.

The read side (:meth:`actor_relations_for`) backs the actor dossier's
Relationships panel; the batch side (indices + :meth:`relation_input_rows` +
:meth:`replace_actor_relations`) backs the full-rebuild pass in
:mod:`eyenet.relations.mentions`. Generic ANSI SQL only.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete
from sqlmodel import col, select

from eyenet.contracts.enums import ActorAliasKind, RelationKind
from eyenet.models.actor import ActorAliasHistoryTable, ActorTable
from eyenet.models.message import MessageTable
from eyenet.models.relation import ActorRelationTable

from ._helpers import safe_session

if TYPE_CHECKING:
    from collections.abc import Sequence

# Read-side row: (other_actor_id, handle, display_name, kind, count, last_seen).
RelationNeighborRow = tuple[UUID, str | None, str | None, RelationKind, int, datetime]
# Write-side edge: (source_id, from_actor, to_actor, kind, count, first_seen, last_seen).
RelationEdgeRow = tuple[UUID, UUID, UUID, RelationKind, int, datetime, datetime]


def _norm(handle: str | None) -> str | None:
    if not handle:
        return None
    return handle.lstrip("@").lower() or None


class RelationsMixin:
    async def handle_to_actor_index(self) -> dict[str, UUID]:
        """Map every known ``@handle`` (normalized, no ``@``, lowercased) to an actor.

        Built from current handles plus handle/username alias history so a mention
        of a since-changed handle still resolves. Current handle wins on collision.
        """
        out: dict[str, UUID] = {}
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            aliases = await session.exec(
                select(ActorAliasHistoryTable.actor_id, ActorAliasHistoryTable.value).where(
                    col(ActorAliasHistoryTable.kind).in_(
                        [ActorAliasKind.HANDLE, ActorAliasKind.USERNAME]
                    )
                )
            )
            for actor_id, value in aliases.all():
                key = _norm(value)
                if key:
                    out[key] = actor_id
            current = await session.exec(
                select(ActorTable.id, ActorTable.current_handle).where(
                    col(ActorTable.current_handle).is_not(None)
                )
            )
            for actor_id, handle in current.all():
                key = _norm(handle)
                if key:
                    out[key] = actor_id
        return out

    async def actor_id_by_platform_userid(self) -> dict[str, UUID]:
        """Map platform_userid -> actor_id (resolves a forward's relayer)."""
        out: dict[str, UUID] = {}
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(ActorTable.platform_userid, ActorTable.id))
            for userid, actor_id in result.all():
                out[str(userid)] = actor_id
        return out

    async def relation_input_rows(
        self,
    ) -> list[tuple[UUID, str | None, datetime, UUID, UUID | None, str | None]]:
        """Every message reduced to relation-builder inputs.

        Returns (from_actor, body, sent_at, source_id, forward_origin_actor,
        relayed_by_platform_userid). The relayer id is pulled from the message's
        ``source_specific`` JSON. One pass, small-operator scale.
        """
        out: list[tuple[UUID, str | None, datetime, UUID, UUID | None, str | None]] = []
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(MessageTable))
            for msg in result.all():
                relayed_by = None
                if isinstance(msg.source_specific, dict):
                    relayed_by = msg.source_specific.get("relayed_by_platform_userid")
                out.append(
                    (
                        msg.actor_id,
                        msg.body,
                        msg.sent_at_source,
                        msg.source_id,
                        msg.forward_origin_actor_id,
                        str(relayed_by) if relayed_by is not None else None,
                    )
                )
        return out

    async def replace_actor_relations(self, edges: Sequence[RelationEdgeRow]) -> None:
        """Full-rebuild the ``actor_relation`` edge set in one transaction.

        Delete-all then bulk insert: the builder is a pure function of the whole
        corpus, so a replace is simpler and race-free versus per-edge upserts.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            await session.exec(delete(ActorRelationTable))
            for source_id, from_actor, to_actor, kind, count, first, last in edges:
                session.add(
                    ActorRelationTable(
                        source_id=source_id,
                        from_actor_id=from_actor,
                        to_actor_id=to_actor,
                        kind=kind,
                        occurrence_count=count,
                        first_seen_at_source=first,
                        last_seen_at_source=last,
                    )
                )
            await session.commit()

    async def actor_relations_for(
        self, actor_id: UUID, *, limit: int = 50
    ) -> tuple[list[RelationNeighborRow], list[RelationNeighborRow]]:
        """Return (outbound, inbound) relation neighbors for an actor.

        Outbound = edges this actor originates (mentioned/relayed someone); inbound
        = edges pointing at this actor. Each row joins the OTHER actor for its
        current handle + display name. Ordered by occurrence count desc.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            outbound = await self._relation_side(session, actor_id, outgoing=True, limit=limit)
            inbound = await self._relation_side(session, actor_id, outgoing=False, limit=limit)
        return outbound, inbound

    async def _relation_side(
        self, session: object, actor_id: UUID, *, outgoing: bool, limit: int
    ) -> list[RelationNeighborRow]:
        anchor = col(
            ActorRelationTable.from_actor_id if outgoing else ActorRelationTable.to_actor_id
        )
        other = col(
            ActorRelationTable.to_actor_id if outgoing else ActorRelationTable.from_actor_id
        )
        stmt = (
            select(ActorRelationTable, ActorTable)
            .join(ActorTable, other == col(ActorTable.id))
            .where(anchor == actor_id)
            .order_by(col(ActorRelationTable.occurrence_count).desc())
            .limit(limit)
        )
        result = await session.exec(stmt)  # type: ignore[attr-defined]
        return [
            (
                actor.id,
                actor.current_handle,
                actor.current_display_name,
                rel.kind,
                rel.occurrence_count,
                rel.last_seen_at_source,
            )
            for rel, actor in result.all()
        ]
