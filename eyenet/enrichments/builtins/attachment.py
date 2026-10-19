# SPDX-License-Identifier: AGPL-3.0-or-later
"""ATTACHMENTS as graph nodes — files on a message (kind/mime/size/sha256 + tier).

Two hops synthesize them straight from AttachmentTable (attachments are not search-indexed;
like documents they carry an effective sensitivity tier):

* ``message -> attachments`` — the files on one message.
* ``actor -> attachments`` — every file the actor posted (attachment -> its message ->
  actor). The message is the evidence anchor, but this one-hop skips the message expansion
  for an actor-centric view.

Each node carries its effective tier in ``fields.tier`` so the API layer can drop
over-clearance attachments from the neighbour set (the enrichment has no caller context;
clearance is filtered in ``api_expand`` via eyenet.api.v1._clearance).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func
from sqlmodel import col, select

from eyenet.enrichments.base import Enrichment, ExpandContext, ExpandNode, ExpandResult
from eyenet.models import AttachmentTable, MessageTable

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel.sql.expression import SelectOfScalar

_A = AttachmentTable


def _attachment_node(a: AttachmentTable) -> ExpandNode:
    kind = a.kind.value
    tier = (a.operator_tier_override or a.classifier_tier).value
    return ExpandNode(
        entity_type="attachment",
        entity_id=a.id,
        title=a.filename or kind,
        status=None,
        source_id=None,
        fields={
            "kind": kind,
            "mime": a.mime,
            "size_bytes": a.size_bytes,
            "filename": a.filename,
            "sha256": a.sha256,
            "tier": tier,
            # present when we stored the bytes; else source_ref is the operator's
            # retrieval link for a blob kept metadata-only (over the size gate).
            "stored": a.storage_uri is not None,
            "source_ref": a.source_ref,
        },
    )


class MessageAttachments(Enrichment):
    """A message's file attachments. Clearance-filtered downstream (fields.tier)."""

    src_type = "message"
    name = "attachments"
    output_type = "attachment"
    edge_kind = "attached"
    countable = True

    async def neighbors(
        self, ctx: ExpandContext, src_id: UUID, *, limit: int, offset: int, want_total: bool
    ) -> ExpandResult:
        base = select(_A).where(col(_A.message_id) == src_id)
        paged = base.order_by(col(_A.id)).offset(offset).limit(limit + 1)
        rows = list(await ctx.session.exec(paged))
        has_more = len(rows) > limit
        nodes = [_attachment_node(a) for a in rows[:limit]]
        total = None
        if want_total:
            total = int(
                (await ctx.session.exec(select(func.count()).select_from(base.subquery()))).one()
            )
        edges = [{"src_id": src_id, "dst_id": n.entity_id, "kind": self.edge_kind} for n in nodes]
        return ExpandResult(nodes=nodes, edges=edges, total=total, has_more=has_more)

    async def count(self, ctx: ExpandContext, src_id: UUID) -> int:
        base = select(func.count()).select_from(
            select(_A).where(col(_A.message_id) == src_id).subquery()
        )
        return int((await ctx.session.exec(base)).one())


class ActorAttachments(Enrichment):
    """Every file an actor posted (attachment -> its message -> actor). Clearance-filtered
    downstream (fields.tier)."""

    src_type = "actor"
    name = "attachments"
    output_type = "attachment"
    edge_kind = "posted"
    countable = True

    def _base(self, src_id: UUID) -> SelectOfScalar[AttachmentTable]:
        # attachment JOIN message ON message.id = attachment.message_id WHERE actor = src
        return (
            select(_A)
            .join(MessageTable, col(_A.message_id) == col(MessageTable.id))
            .where(col(MessageTable.actor_id) == src_id)
        )

    async def neighbors(
        self, ctx: ExpandContext, src_id: UUID, *, limit: int, offset: int, want_total: bool
    ) -> ExpandResult:
        base = self._base(src_id)
        paged = base.order_by(col(_A.id)).offset(offset).limit(limit + 1)
        rows = list(await ctx.session.exec(paged))
        has_more = len(rows) > limit
        nodes = [_attachment_node(a) for a in rows[:limit]]
        total = None
        if want_total:
            total = int(
                (await ctx.session.exec(select(func.count()).select_from(base.subquery()))).one()
            )
        edges = [{"src_id": src_id, "dst_id": n.entity_id, "kind": self.edge_kind} for n in nodes]
        return ExpandResult(nodes=nodes, edges=edges, total=total, has_more=has_more)

    async def count(self, ctx: ExpandContext, src_id: UUID) -> int:
        base = select(func.count()).select_from(self._base(src_id).subquery())
        return int((await ctx.session.exec(base)).one())
