# SPDX-License-Identifier: AGPL-3.0-or-later
"""message -> its ATTACHMENTS (files on the message: kind/mime/size/sha256 + tier).

Attachments are not search-indexed (like documents, they carry an effective sensitivity
tier), so this synthesizes the node straight from AttachmentTable. The node carries its
effective tier in ``fields.tier`` so the API layer can drop over-clearance attachments from
the neighbour set (the enrichment has no caller context; clearance is filtered in
``api_expand`` via eyenet.api.v1._clearance).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func
from sqlmodel import col, select

from eyenet.enrichments.base import Enrichment, ExpandContext, ExpandNode, ExpandResult
from eyenet.models import AttachmentTable

if TYPE_CHECKING:
    from uuid import UUID

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
