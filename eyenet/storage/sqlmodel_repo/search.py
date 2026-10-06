# SPDX-License-Identifier: AGPL-3.0-or-later
"""SearchMixin — global cross-entity search over `search_document` (GLOBAL_SEARCH.md).

Generic, dialect-free layer (Rule 1): the free-text predicate is ANSI
``LOWER(col) LIKE '%q%'`` via the ``_search_predicate`` seam, overridden on the
concrete backends with FTS (SQLite FTS5, Postgres ``tsvector`` + ``pg_trgm``).
Bulk upsert is SELECT-then-add here; the concrete backends override with an
atomic ``ON CONFLICT (entity_type, entity_id)``.

All methods run on the MAIN store (`self._session_factory`) — `search_document`
lives in `main.db` / `main`, like `message_fts`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence
from itertools import combinations
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, func, or_
from sqlmodel import col, select

from eyenet.models import (
    ActorArtifactTable,
    ActorRelationTable,
    LinkageTable,
    MessageTable,
    PersonaMembershipTable,
    SearchDocumentTable,
)
from eyenet.models._base import now_utc

from ._helpers import safe_session

# Result ordering: lower rank shown first. Identity-ish entities outrank bulk
# content so an actor whose handle IS the query beats a message mentioning it.
# Relevance tuning (handle-vs-prose, bm25/ts_rank blending) is Phase 3.
_TYPE_RANK: dict[str, int] = {
    "actor": 0,
    "persona": 1,
    "crew": 2,
    "artifact": 3,
    "case": 4,
    "group": 5,
    "thread": 6,
    "document": 7,
    "mention": 8,
    "message": 9,
    "attachment": 10,
    "incident": 11,
}
_DEFAULT_RANK = 99

# Columns the indexer writes; used to coerce an upsert payload.
_COLUMNS = (
    "entity_type",
    "entity_id",
    "source_id",
    "status",
    "title",
    "subtitle",
    "haystack",
    "handles",
    "fields",
    "updated_at",
)


class SearchMixin:
    # ---- dialect seam -----------------------------------------------------
    def _search_predicate(self, q: str) -> Any:
        """Generic ANSI substring match over haystack + handles.

        Concrete backends override with FTS. Rule 1: no dialect SQL here.
        """
        pattern = f"%{q.lower()}%"
        return or_(
            func.lower(col(SearchDocumentTable.haystack)).like(pattern),
            func.lower(func.coalesce(col(SearchDocumentTable.handles), "")).like(pattern),
        )

    @staticmethod
    def _type_rank() -> Any:
        return case(_TYPE_RANK, value=col(SearchDocumentTable.entity_type), else_=_DEFAULT_RANK)

    @staticmethod
    def _apply_filters(
        stmt: Any,
        *,
        types: Sequence[str] | None,
        status: Sequence[str] | None,
        source_id: UUID | None,
    ) -> Any:
        if types:
            stmt = stmt.where(col(SearchDocumentTable.entity_type).in_(list(types)))
        if status:
            stmt = stmt.where(col(SearchDocumentTable.status).in_(list(status)))
        if source_id is not None:
            stmt = stmt.where(SearchDocumentTable.source_id == source_id)
        return stmt

    # ---- reads ------------------------------------------------------------
    async def search_global(
        self,
        q: str,
        *,
        types: Sequence[str] | None = None,
        status: Sequence[str] | None = None,
        source_id: UUID | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[object]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(SearchDocumentTable).where(self._search_predicate(q))
            stmt = self._apply_filters(stmt, types=types, status=status, source_id=source_id)
            stmt = (
                stmt.order_by(self._type_rank())
                .order_by(col(SearchDocumentTable.updated_at).desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.exec(stmt)
            return list(result)

    async def count_search_global(
        self,
        q: str,
        *,
        types: Sequence[str] | None = None,
        status: Sequence[str] | None = None,
        source_id: UUID | None = None,
    ) -> int:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(func.count())
                .select_from(SearchDocumentTable)
                .where(self._search_predicate(q))
            )
            stmt = self._apply_filters(stmt, types=types, status=status, source_id=source_id)
            result = await session.exec(stmt)
            return int(result.one())

    async def search_global_facets(
        self,
        q: str,
        *,
        types: Sequence[str] | None = None,
        status: Sequence[str] | None = None,
        source_id: UUID | None = None,
    ) -> dict[str, dict[str, int]]:
        """``{"by_type": {...}, "by_source": {...}}``.

        by_type ignores the ``types`` filter (so the UI shows every type's count
        to pivot into); by_source ignores the ``source_id`` filter likewise.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            # by_type: apply status + source, NOT types.
            t_stmt = (
                select(col(SearchDocumentTable.entity_type), func.count())
                .where(self._search_predicate(q))
                .group_by(col(SearchDocumentTable.entity_type))
            )
            t_stmt = self._apply_filters(t_stmt, types=None, status=status, source_id=source_id)
            by_type = {str(k): int(v) for k, v in (await session.exec(t_stmt)).all()}

            # by_source: apply types + status, NOT source.
            s_stmt = (
                select(col(SearchDocumentTable.source_id), func.count())
                .where(self._search_predicate(q))
                .group_by(col(SearchDocumentTable.source_id))
            )
            s_stmt = self._apply_filters(s_stmt, types=types, status=status, source_id=None)
            by_source = {
                (str(k) if k is not None else ""): int(v)
                for k, v in (await session.exec(s_stmt)).all()
            }
        return {"by_type": by_type, "by_source": by_source}

    # ---- writes (generic SELECT-then-add; backends override bulk) ----------
    @staticmethod
    def _coerce(fields: dict[str, Any]) -> dict[str, Any]:
        row = {k: fields.get(k) for k in _COLUMNS}
        if row.get("updated_at") is None:
            row["updated_at"] = now_utc()
        if row.get("title") is None:
            row["title"] = ""
        if row.get("haystack") is None:
            row["haystack"] = ""
        if row.get("fields") is None:
            row["fields"] = {}
        return row

    async def put_search_documents_bulk(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            for raw in rows:
                r = self._coerce(dict(raw))
                existing = (
                    await session.exec(
                        select(SearchDocumentTable).where(
                            SearchDocumentTable.entity_type == r["entity_type"],
                            SearchDocumentTable.entity_id == r["entity_id"],
                        )
                    )
                ).first()
                if existing is None:
                    session.add(SearchDocumentTable(**r))
                else:
                    for k, v in r.items():
                        setattr(existing, k, v)
                    session.add(existing)
            await session.commit()

    async def put_search_document(self, **fields: Any) -> None:
        await self.put_search_documents_bulk([fields])

    async def delete_search_document(self, entity_type: str, entity_id: UUID) -> None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            existing = (
                await session.exec(
                    select(SearchDocumentTable).where(
                        SearchDocumentTable.entity_type == entity_type,
                        SearchDocumentTable.entity_id == entity_id,
                    )
                )
            ).first()
            if existing is not None:
                await session.delete(existing)
                await session.commit()

    async def induced_edges(
        self,
        *,
        actor_ids: Collection[UUID],
        persona_ids: Collection[UUID],
        artifact_ids: Collection[UUID],
        thread_ids: Collection[UUID] = (),
    ) -> list[dict[str, Any]]:
        """Derived edges among the search-result nodes (GLOBAL_SEARCH.md §10.3).

        Scoped to the given node ids: linkage + actor_relation (actor-actor),
        shared-infra (two node-actors on one artifact) + actor-artifact, persona
        membership, and ``same_author`` among threads whose OP is the same actor
        (free: the OP is provably one entity, so the operator needn't hand-link
        them). Each edge is a dict the API maps to the wire shape; ``provenance``
        is stamped "derived" by the caller.
        """
        a_ids = list(actor_ids)
        edges: list[dict[str, Any]] = []
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            await self._same_author_thread_edges(session, list(thread_ids), edges)
            if a_ids:
                links = await session.exec(
                    select(LinkageTable).where(
                        col(LinkageTable.actor_a_id).in_(a_ids),
                        col(LinkageTable.actor_b_id).in_(a_ids),
                    )
                )
                for lk in links:
                    edges.append(
                        {
                            "src_id": lk.actor_a_id,
                            "dst_id": lk.actor_b_id,
                            "kind": "linked",
                            "weight": lk.score,
                            "meta": {"state": _enum(lk.state), "method": lk.method},
                        }
                    )
                rels = await session.exec(
                    select(ActorRelationTable).where(
                        col(ActorRelationTable.from_actor_id).in_(a_ids),
                        col(ActorRelationTable.to_actor_id).in_(a_ids),
                    )
                )
                for rel in rels:
                    edges.append(
                        {
                            "src_id": rel.from_actor_id,
                            "dst_id": rel.to_actor_id,
                            "kind": _enum(rel.kind),
                            "weight": float(rel.occurrence_count),
                            "meta": {},
                        }
                    )
                # actor -> artifact (when the artifact is also a node) + the
                # actor<->actor shared-infra edge (two node-actors on one artifact).
                aa = list(
                    await session.exec(
                        select(ActorArtifactTable).where(
                            col(ActorArtifactTable.actor_id).in_(a_ids)
                        )
                    )
                )
                art_set = set(artifact_ids)
                actors_by_artifact: dict[UUID, list[UUID]] = defaultdict(list)
                for row in aa:
                    actors_by_artifact[row.artifact_id].append(row.actor_id)
                    if row.artifact_id in art_set:
                        edges.append(
                            {
                                "src_id": row.actor_id,
                                "dst_id": row.artifact_id,
                                "kind": "uses_infra",
                                "weight": row.confidence,
                                "meta": {},
                            }
                        )
                for art_id, actors in actors_by_artifact.items():
                    for x, y in combinations(sorted(set(actors)), 2):
                        edges.append(
                            {
                                "src_id": x,
                                "dst_id": y,
                                "kind": "shares_infra",
                                "weight": None,
                                "meta": {"artifact_id": str(art_id)},
                            }
                        )
                if persona_ids:
                    pm = await session.exec(
                        select(PersonaMembershipTable).where(
                            col(PersonaMembershipTable.actor_id).in_(a_ids),
                            col(PersonaMembershipTable.persona_id).in_(list(persona_ids)),
                        )
                    )
                    for m in pm:
                        edges.append(
                            {
                                "src_id": m.actor_id,
                                "dst_id": m.persona_id,
                                "kind": "member_of_persona",
                                "weight": None,
                                "meta": {},
                            }
                        )
        return edges

    # Small clusters get a full mesh (every pair of a prolific author's threads is
    # related); big clusters star on one hub thread so the graph stays readable.
    _SAME_AUTHOR_MESH_MAX = 5

    async def _same_author_thread_edges(
        self, session: Any, thread_ids: list[UUID], edges: list[dict[str, Any]]
    ) -> None:
        """Append ``same_author`` edges among threads whose OP (earliest message)
        is the same actor. The node set is capped (<=500) upstream, so a single IN
        is safe — no chunking.
        """
        if not thread_ids:
            return
        earliest = (
            select(
                MessageTable.group_id,
                func.min(MessageTable.sent_at_source).label("mn"),
            )
            .where(col(MessageTable.group_id).in_(thread_ids))
            .group_by(col(MessageTable.group_id))
            .subquery()
        )
        ops = await session.exec(
            select(MessageTable.group_id, MessageTable.actor_id).join(
                earliest,
                and_(
                    col(MessageTable.group_id) == earliest.c.group_id,
                    col(MessageTable.sent_at_source) == earliest.c.mn,
                ),
            )
        )
        threads_by_author: dict[UUID, list[UUID]] = defaultdict(list)
        seen: set[UUID] = set()
        for gid, aid in ops:
            if gid in seen:  # a timestamp tie yields >1 OP row; keep the first
                continue
            seen.add(gid)
            threads_by_author[aid].append(gid)
        for aid, ths in threads_by_author.items():
            uniq = sorted(set(ths))
            if len(uniq) <= 1:
                continue
            if len(uniq) <= self._SAME_AUTHOR_MESH_MAX:
                pairs: Any = combinations(uniq, 2)
            else:
                hub = uniq[0]
                pairs = ((hub, t) for t in uniq[1:])
            for x, y in pairs:
                edges.append(
                    {
                        "src_id": x,
                        "dst_id": y,
                        "kind": "same_author",
                        "weight": None,
                        "meta": {"actor_id": str(aid)},
                    }
                )


def _enum(v: Any) -> str:
    return v.value if hasattr(v, "value") else str(v)


__all__ = ["SearchMixin"]
