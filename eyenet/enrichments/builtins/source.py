# SPDX-License-Identifier: AGPL-3.0-or-later
"""<entity> -> its collector SOURCE (Telegram, Pwnforums, Raidforums, ...).

Every actor/message/group row carries a non-null ``source_id`` FK, so this is a single
neighbour: the one Source the entity was collected from, surfaced so the operator can tell
at a glance where a node came from.

Source is a COARSE origin for now - one Telegram account spans many channels, a forum
source spans all its categories/threads - but it answers "which board/platform is this?".

Source rows are NOT search-indexed, so (unlike the LocalSQLEnrichment built-ins, which
hydrate neighbour ids from ``search_document``) these synthesize the source node directly
from ``SourceTable``.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from eyenet.enrichments.base import Enrichment, ExpandContext, ExpandNode, ExpandResult
from eyenet.models import ActorTable, GroupTable, MessageTable, SourceTable

if TYPE_CHECKING:
    from uuid import UUID


class _SourceEnrichment(Enrichment):
    """Shared actor/message/group -> source hop. Abstract (no ``_entity_table``), so
    autodiscovery registers only the concrete per-src_type subclasses below."""

    name = "source"
    output_type = "source"
    edge_kind = "from_source"
    single = True
    countable = True

    @abstractmethod
    def _entity_table(self) -> type:
        """The SQLModel table holding the ``source_id`` FK for this src_type."""

    async def _source_id(self, ctx: ExpandContext, src_id: UUID) -> UUID | None:
        row = await ctx.session.get(self._entity_table(), src_id)
        return getattr(row, "source_id", None) if row is not None else None

    async def neighbors(
        self,
        ctx: ExpandContext,
        src_id: UUID,
        *,
        limit: int,  # noqa: ARG002 — single neighbour; pagination args unused
        offset: int,  # noqa: ARG002
        want_total: bool,
    ) -> ExpandResult:
        sid = await self._source_id(ctx, src_id)
        source = await ctx.session.get(SourceTable, sid) if sid is not None else None
        if source is None:
            return ExpandResult(nodes=[], edges=[], total=0 if want_total else None, has_more=False)
        node = ExpandNode(
            entity_type="source",
            entity_id=source.id,
            title=source.display_name,
            status=None,
            source_id=None,
            fields={"kind": source.kind.value, "canonical_url": source.canonical_url},
        )
        edges = [{"src_id": src_id, "dst_id": source.id, "kind": self.edge_kind}]
        return ExpandResult(
            nodes=[node], edges=edges, total=1 if want_total else None, has_more=False
        )

    async def count(self, ctx: ExpandContext, src_id: UUID) -> int:
        return 1 if await self._source_id(ctx, src_id) is not None else 0


class ActorSource(_SourceEnrichment):
    src_type = "actor"

    def _entity_table(self) -> type:
        return ActorTable


class MessageSource(_SourceEnrichment):
    src_type = "message"

    def _entity_table(self) -> type:
        return MessageTable


class GroupSource(_SourceEnrichment):
    src_type = "group"

    def _entity_table(self) -> type:
        return GroupTable


class ThreadSource(_SourceEnrichment):
    # 'thread' entities ARE GroupTable rows (forum threads) - same source_id FK.
    src_type = "thread"

    def _entity_table(self) -> type:
        return GroupTable
