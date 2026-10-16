# SPDX-License-Identifier: AGPL-3.0-or-later
"""Enrichment plugin interface for the graph exploration canvas.

An enrichment is one hop from a source node along a single relation: given a
source ``(src_type, src_id)`` it returns the neighbour nodes + the edges to them.
Two execution models:

* :class:`LocalSQLEnrichment` - the neighbours are rows in our own DB. The plugin
  only builds a SELECT of the neighbour ids; the base runs it, paginates, and
  hydrates each id from ``search_document`` into an :class:`ExpandNode`. All the
  built-ins are this.
* :class:`RemoteEnrichment` - the neighbours come from an external service (e.g.
  a blockchain API). The plugin fetches them and synthesizes the nodes directly.

Plugins are discovered automatically (see :mod:`eyenet.enrichments.registry`):
drop a module with a concrete subclass into ``builtins/`` or ``remote/`` and it is
registered by ``(src_type, name)``. No central dispatch to edit.

This module imports only models + sqlmodel, never ``eyenet.storage`` (storage
imports the registry, so the dependency runs one way).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import func
from sqlmodel import col, select

from eyenet.models import SearchDocumentTable

if TYPE_CHECKING:
    from uuid import UUID


@dataclass
class ExpandNode:
    """A neighbour node, wire-compatible with the search-graph node shape (same
    attributes a ``search_document`` row exposes, so the API maps either one)."""

    entity_type: str
    entity_id: UUID
    title: str | None
    status: str | None
    source_id: UUID | None
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExpandResult:
    """One enrichment hop's output. ``edges`` are ``{src_id, dst_id, kind}`` dicts
    (always source -> neighbour). ``total`` is ``None`` unless a total was asked for."""

    nodes: list[ExpandNode]
    edges: list[dict[str, Any]]
    total: int | None
    has_more: bool


@dataclass
class ExpandContext:
    """Execution context handed to an enrichment. ``session`` is the open
    ``AsyncSession`` (local SQL + hydration); ``repo`` is the repository itself
    (duck-typed ``BaseRepository``) for remote enrichments that must resolve the
    source entity's value or dedup discovered nodes against the corpus."""

    session: Any
    repo: Any = None

    async def hydrate(self, ids: list[UUID]) -> list[ExpandNode]:
        """``search_document`` rows for ``ids``, in input order, as ExpandNodes;
        ids not present in the search index are dropped (unindexed entity types)."""
        if not ids:
            return []
        result = await self.session.exec(
            select(SearchDocumentTable).where(col(SearchDocumentTable.entity_id).in_(ids))
        )
        by_id = {r.entity_id: r for r in result}
        out: list[ExpandNode] = []
        for i in ids:
            row = by_id.get(i)
            if row is not None:
                out.append(
                    ExpandNode(
                        entity_type=row.entity_type,
                        entity_id=row.entity_id,
                        title=row.title,
                        status=row.status,
                        source_id=row.source_id,
                        fields=row.fields or {},
                    )
                )
        return out


class Enrichment(ABC):
    """One named enrichment for one source entity type.

    Concrete subclasses set the class-level metadata. Contributors normally
    subclass :class:`LocalSQLEnrichment` (DB-backed) or :class:`RemoteEnrichment`
    (external) rather than this directly.
    """

    src_type: str
    name: str
    output_type: str
    edge_kind: str
    single: bool = False
    tier_gated: bool = False

    async def applicable(self, ctx: ExpandContext, src_id: UUID) -> bool:  # noqa: ARG002
        """Whether this enrichment applies to this specific source (the counts
        endpoint skips non-applicable ones). Built-ins always apply; a remote
        enrichment keyed to a specific artifact kind overrides this."""
        return True

    @abstractmethod
    async def neighbors(
        self, ctx: ExpandContext, src_id: UUID, *, limit: int, offset: int, want_total: bool
    ) -> ExpandResult: ...

    @abstractmethod
    async def count(self, ctx: ExpandContext, src_id: UUID) -> int: ...


class LocalSQLEnrichment(Enrichment):
    """An enrichment whose neighbours are ids in our own DB. Subclasses implement
    only :meth:`build_select`; the paginate + hydrate logic is shared (and is the
    exact logic the former hardcoded ``GraphExpandMixin`` used)."""

    @abstractmethod
    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        """``(stmt, id_column)`` selecting the neighbour-id column. Unordered (the
        base adds order/limit/offset or wraps it in COUNT); a ``single`` enrichment
        may carry its own ordering + limit(1)."""

    async def neighbors(
        self, ctx: ExpandContext, src_id: UUID, *, limit: int, offset: int, want_total: bool
    ) -> ExpandResult:
        base, idcol = self.build_select(src_id)
        if self.single:
            rows = [r for r in await ctx.session.exec(base) if r is not None][:1]
            page_ids, has_more = rows, False
            total = len(rows) if want_total else None
        else:
            paged = base.order_by(idcol).offset(offset).limit(limit + 1)
            fetched = [r for r in await ctx.session.exec(paged) if r is not None]
            has_more = len(fetched) > limit
            page_ids = fetched[:limit]
            total = None
            if want_total:
                total = int(
                    (
                        await ctx.session.exec(select(func.count()).select_from(base.subquery()))
                    ).one()
                )
        nodes = await ctx.hydrate(page_ids)
        edges = [{"src_id": src_id, "dst_id": n.entity_id, "kind": self.edge_kind} for n in nodes]
        return ExpandResult(nodes=nodes, edges=edges, total=total, has_more=has_more)

    async def count(self, ctx: ExpandContext, src_id: UUID) -> int:
        base, _idcol = self.build_select(src_id)
        if self.single:
            return len([r for r in await ctx.session.exec(base) if r is not None][:1])
        return int(
            (await ctx.session.exec(select(func.count()).select_from(base.subquery()))).one()
        )


class RemoteEnrichment(Enrichment):
    """An enrichment whose neighbours come from an external service. Subclasses
    resolve the source entity's value (e.g. a wallet address) then fetch + build
    the nodes. No concrete remote enrichment ships in Phase A; the mempool BTC
    plugin (Phase B) is the first."""

    @abstractmethod
    async def resolve_src_value(self, ctx: ExpandContext, src_id: UUID) -> str:
        """The source entity's external key (e.g. the artifact's value), via
        ``ctx.repo``."""

    @abstractmethod
    async def fetch(
        self, ctx: ExpandContext, src_value: str, *, limit: int, offset: int, want_total: bool
    ) -> ExpandResult:
        """Call the external service and build the neighbour nodes + edges."""

    async def neighbors(
        self, ctx: ExpandContext, src_id: UUID, *, limit: int, offset: int, want_total: bool
    ) -> ExpandResult:
        src_value = await self.resolve_src_value(ctx, src_id)
        return await self.fetch(
            ctx, src_value, limit=limit, offset=offset, want_total=want_total
        )

    async def count(self, ctx: ExpandContext, src_id: UUID) -> int:  # noqa: ARG002
        # Remote degree is not cheaply countable without a fetch; the degree
        # preview shows nothing until expanded. Subclasses may override.
        return 0


__all__ = [
    "Enrichment",
    "ExpandContext",
    "ExpandNode",
    "ExpandResult",
    "LocalSQLEnrichment",
    "RemoteEnrichment",
]
