# SPDX-License-Identifier: AGPL-3.0-or-later
"""Remote enrichment: a domain / subdomain artifact -> its leaked infostealer creds.

The payoff of having the ULP corpus inside EYENET: on a compromised-infra artifact in a
case graph, one expand surfaces the leaked logins for that exact host — an instant lead
on WHICH account to chase. Two enrichments, both EXACT-host match (a subdomain artifact
and its parent-domain artifact are distinct nodes, so neither should net the other's
creds):

* ``infostealer_domain``    - applies to a registrable-domain artifact (fiction.cl)
* ``infostealer_subdomain`` - applies to a subdomain artifact (gov.fiction.cl)

Creds come from ClickHouse (not our DB), so this is a RemoteEnrichment. Each cred is an
ephemeral ``artifact`` node (kind=credential; canvas-only, not persisted) titled by its
login, carrying the password/host in fields for the inspector. Gated by ``read:stealer``
(``required_scope``) so the corpus can't leak into the graph for a read:search operator.
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

import tldextract
from sqlmodel import select

from eyenet.enrichments.base import ExpandContext, ExpandNode, ExpandResult, RemoteEnrichment
from eyenet.models import InfrastructureArtifactTable
from eyenet.stealer.query import StealerCredsReader

if TYPE_CHECKING:
    from eyenet.stealer.query import CredRow

_DOMAIN_KIND = "domain"
_EDGE = "infostealer_leak"
# Namespace for a cred's stable canvas id (host|login|password), so repeat expands keep
# the same node identity across pages.
_NS = uuid5(NAMESPACE_URL, "eyenet:infostealer_cred")
_reader = StealerCredsReader()


async def _artifact(ctx: ExpandContext, src_id: UUID) -> InfrastructureArtifactTable | None:
    row = (
        await ctx.session.exec(
            select(InfrastructureArtifactTable).where(InfrastructureArtifactTable.id == src_id)
        )
    ).first()
    return cast("InfrastructureArtifactTable | None", row)


def _has_subdomain(value: str) -> bool:
    return tldextract.extract(value).subdomain != ""


async def _resolve_domain(ctx: ExpandContext, src_id: UUID) -> str:
    art = await _artifact(ctx, src_id)
    if art is None or art.kind != _DOMAIN_KIND:
        raise ValueError(f"artifact {src_id!r} is not a {_DOMAIN_KIND}")
    return art.value


def _cred_node(c: CredRow) -> ExpandNode:
    return ExpandNode(
        entity_type="artifact",
        entity_id=uuid5(_NS, f"{c.host}|{c.login}|{c.password}"),
        title=c.login or c.host,
        status=None,
        source_id=None,
        fields={
            "kind": "credential",
            "ephemeral": True,
            "host": c.host,
            "login": c.login,
            "password": c.password,
            "scheme": c.scheme,
            "url": c.url,
        },
    )


async def _fetch_creds(
    src_id: UUID, host: str, *, limit: int, offset: int, want_total: bool
) -> ExpandResult:
    # CH client is sync -> run off the event loop. Over-fetch by one for has_more.
    rows = await asyncio.to_thread(
        _reader.search, host=host, limit=limit + 1, offset=offset, exact=True
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    total = await asyncio.to_thread(_reader.count_host, host) if want_total else None
    nodes = [_cred_node(c) for c in page]
    edges: list[dict[str, Any]] = [
        {"src_id": src_id, "dst_id": n.entity_id, "kind": _EDGE} for n in nodes
    ]
    return ExpandResult(nodes=nodes, edges=edges, total=total, has_more=has_more)


class _InfostealerCreds(RemoteEnrichment):
    """Shared behaviour; the two concrete plugins differ only in applicability."""

    src_type = "artifact"
    output_type = "artifact"
    edge_kind = _EDGE
    required_scope = "read:stealer"
    countable = True

    async def resolve_src_value(self, ctx: ExpandContext, src_id: UUID) -> str:
        return await _resolve_domain(ctx, src_id)

    async def fetch(
        self,
        ctx: ExpandContext,  # noqa: ARG002 — creds come from ClickHouse, not ctx.session
        src_id: UUID,
        src_value: str,
        *,
        limit: int,
        offset: int,
        want_total: bool,
    ) -> ExpandResult:
        return await _fetch_creds(
            src_id, src_value, limit=limit, offset=offset, want_total=want_total
        )

    async def count(self, ctx: ExpandContext, src_id: UUID) -> int:
        art = await _artifact(ctx, src_id)
        if art is None:
            return 0
        return await asyncio.to_thread(_reader.count_host, art.value)

    @abstractmethod
    async def applicable(self, ctx: ExpandContext, src_id: UUID) -> bool:
        """Concrete plugins gate on registrable-domain vs subdomain (keeps this base
        abstract so the registry registers only the two concrete plugins)."""


class InfostealerForDomain(_InfostealerCreds):
    """Leaked creds for a registrable-domain artifact (exact host)."""

    name = "infostealer_domain"

    async def applicable(self, ctx: ExpandContext, src_id: UUID) -> bool:
        art = await _artifact(ctx, src_id)
        return art is not None and art.kind == _DOMAIN_KIND and not _has_subdomain(art.value)


class InfostealerForSubdomain(_InfostealerCreds):
    """Leaked creds for a subdomain artifact (exact host)."""

    name = "infostealer_subdomain"

    async def applicable(self, ctx: ExpandContext, src_id: UUID) -> bool:
        art = await _artifact(ctx, src_id)
        return art is not None and art.kind == _DOMAIN_KIND and _has_subdomain(art.value)


__all__ = ["InfostealerForDomain", "InfostealerForSubdomain"]
