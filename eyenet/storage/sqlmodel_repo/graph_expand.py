# SPDX-License-Identifier: AGPL-3.0-or-later
"""GraphExpandMixin - neighbor expansion for the ``/v1/graph/expand`` explorer.

Given ONE node ``(entity_type, entity_id)`` and an enrichment name, return its
neighbours along a single relation. The enrichment logic lives in the
autodiscovered plugin registry (:mod:`eyenet.enrichments`); this mixin just opens
a session, builds the :class:`~eyenet.enrichments.base.ExpandContext`, and runs
the looked-up enrichment. Add an enrichment by dropping a plugin module in
``eyenet/enrichments/`` - no edit here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from eyenet.enrichments import (
    ExpandContext,
    ExpandNode,
    enrichments_for_src_type,
    get_enrichment,
)

from ._helpers import safe_session

if TYPE_CHECKING:
    from uuid import UUID


class GraphExpandMixin:
    async def graph_expand(
        self,
        *,
        src_type: str,
        src_id: UUID,
        enrichment: str,
        limit: int,
        offset: int,
        want_total: bool,
    ) -> tuple[list[ExpandNode], list[dict[str, Any]], int | None, bool]:
        """Neighbours of ``(src_type, src_id)`` along ``enrichment``.

        Returns ``(nodes, edges, total, has_more)``. ``edges`` are dicts
        ``{src_id, dst_id, kind}`` (always source -> neighbour). ``total`` is
        ``None`` unless ``want_total``. Raises ``ValueError`` for an unknown
        ``(src_type, enrichment)``.
        """
        enr = get_enrichment(src_type, enrichment)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            ctx = ExpandContext(session=session, repo=self)
            result = await enr.neighbors(
                ctx, src_id, limit=limit, offset=offset, want_total=want_total
            )
            return result.nodes, result.edges, result.total, result.has_more

    async def graph_expand_counts(
        self, *, src_type: str, src_id: UUID
    ) -> dict[str, int | None]:
        """Per-enrichment neighbour totals for the degree preview. A remote
        enrichment has no cheap count, so its value is ``None`` (available, count
        unknown). Unknown ``src_type`` raises ``ValueError``."""
        enrichments = enrichments_for_src_type(src_type)
        if not enrichments:
            raise ValueError(f"unknown entity type {src_type!r}")
        out: dict[str, int | None] = {}
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            ctx = ExpandContext(session=session, repo=self)
            for enr in enrichments:
                if await enr.applicable(ctx, src_id):
                    out[enr.name] = await enr.count(ctx, src_id) if enr.countable else None
        return out
