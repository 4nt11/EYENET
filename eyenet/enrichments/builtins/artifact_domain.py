# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL artifact -> its host artifact (the ``domain``/``onion``/``ip`` it points at).

Deterministic and safe: the host lives inside the URL string, so one URL has exactly one
host (single neighbour, no cross-actor misattribution). The dangerous reverse - a host to
all its URLs/subdomains - is deliberately NOT here; associating many URLs to a domain
across different actors would misattribute, so that belongs to a future message-scoped /
external-discovery (crt.sh, global scan) enrichment on the domain itself.

The url-extraction pass stores a host artifact's value as the FULL host (``normalize_host``
for domains, raw for onion/IP), so this is an exact full-host match on the indexed
``value_hash`` - an index hit, not a scan.
"""

from __future__ import annotations

import contextlib
import hashlib
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

from sqlmodel import col, select

from eyenet.enrichments.base import Enrichment, ExpandContext, ExpandNode, ExpandResult
from eyenet.models import InfrastructureArtifactTable
from eyenet.util.domain import normalize_host

if TYPE_CHECKING:
    from uuid import UUID

_IA = InfrastructureArtifactTable
# Host-carrying artifact kinds a URL can point at.
_HOST_KINDS = ("domain", "onion", "ipv4", "ipv6")


def _sha(value: str) -> str:
    # Mirrors storage._value_hash; computed inline because enrichments must not import
    # eyenet.storage (storage imports the registry - the dependency runs one way).
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ArtifactDomain(Enrichment):
    src_type = "artifact"
    name = "domain"
    output_type = "artifact"
    edge_kind = "on_domain"
    single = True
    countable = True

    async def _host_row(
        self, ctx: ExpandContext, src_id: UUID
    ) -> InfrastructureArtifactTable | None:
        art = await ctx.session.get(_IA, src_id)
        if art is None or art.kind != "url":
            return None
        host = (urlsplit(art.value).hostname or "").strip().rstrip(".").lower()
        if not host:
            return None
        candidates = {host}
        # Add the IDNA form (how domains are stored) when the host is IDNA-able; onion/IP
        # hosts aren't, and the raw host already covers those, so a ValueError is expected.
        with contextlib.suppress(ValueError):
            candidates.add(normalize_host(host))
        hashes = [_sha(c) for c in candidates]
        result = await ctx.session.exec(
            select(_IA)
            .where(col(_IA.kind).in_(_HOST_KINDS), col(_IA.value_hash).in_(hashes))
            .limit(1)
        )
        return cast("InfrastructureArtifactTable | None", result.first())

    async def applicable(self, ctx: ExpandContext, src_id: UUID) -> bool:
        art = await ctx.session.get(_IA, src_id)
        return art is not None and art.kind == "url"

    async def neighbors(
        self,
        ctx: ExpandContext,
        src_id: UUID,
        *,
        limit: int,  # noqa: ARG002 — single neighbour; pagination args unused
        offset: int,  # noqa: ARG002
        want_total: bool,
    ) -> ExpandResult:
        row = await self._host_row(ctx, src_id)
        if row is None:
            return ExpandResult(nodes=[], edges=[], total=0 if want_total else None, has_more=False)
        node = ExpandNode(
            entity_type="artifact",
            entity_id=row.id,
            title=row.value,
            status=None,
            source_id=None,
            fields={"kind": row.kind, "value": row.value},
        )
        edges = [{"src_id": src_id, "dst_id": row.id, "kind": self.edge_kind}]
        return ExpandResult(
            nodes=[node], edges=edges, total=1 if want_total else None, has_more=False
        )

    async def count(self, ctx: ExpandContext, src_id: UUID) -> int:
        return 1 if await self._host_row(ctx, src_id) is not None else 0
