# SPDX-License-Identifier: AGPL-3.0-or-later
"""Remote enrichment: BTC wallet -> connected wallets via a mempool REST API.

On-demand only (one fetch per operator expand, never a background poll). Given a
``btc_wallet`` artifact, pulls the address's recent transactions from a mempool.space
style REST API and returns the counterparty addresses as artifact nodes, with
DIRECTIONAL edges:
* ``sent_to``      - our address was a tx input, theirs an output (we paid them)
* ``received_from``- our address was an output, theirs an input (they paid us)
A counterparty already in our corpus (matched by value_hash) comes back as the REAL
node (its id); genuinely new ones are ephemeral (uuid5-stable, canvas-only) until
the operator persists them via ``POST /v1/artifacts`` (operator-asserted create).

OPSEC: querying a public mempool instance reveals which addresses you investigate.
Point ``EYENET_MEMPOOL_API_BASE`` at a self-hosted or .onion mempool for real work.

Rate limits: mempool.space does not publish them, so this fires at most one request
per expand and caches each address's txs briefly (``EYENET_MEMPOOL_CACHE_TTL``) so
repeat expands of the same node do not re-hit the API.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from sqlmodel import col, select

from eyenet.enrichments.base import (
    ExpandContext,
    ExpandNode,
    ExpandResult,
    RemoteEnrichment,
)
from eyenet.models import InfrastructureArtifactTable

MEMPOOL_API_BASE = os.environ.get("EYENET_MEMPOOL_API_BASE", "https://mempool.space/api")
_TIMEOUT = float(os.environ.get("EYENET_MEMPOOL_TIMEOUT", "10"))
_CACHE_TTL = float(os.environ.get("EYENET_MEMPOOL_CACHE_TTL", "60"))
_BTC_KIND = "btc_wallet"
_NS = uuid5(NAMESPACE_URL, "eyenet:btc_wallet")

SENT_TO = "sent_to"
RECEIVED_FROM = "received_from"

# address -> (expiry_monotonic, txs). Module-level so repeat expands within the TTL
# reuse one fetch. Cleared in tests via _clear_cache().
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _clear_cache() -> None:
    _cache.clear()


def _value_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ephemeral_id(address: str) -> UUID:
    """Stable synthetic id for an address not (yet) in our DB, so the canvas node
    keeps its identity across expands until the operator adds it to the DB."""
    return uuid5(_NS, address)


async def _http_get_txs(address: str) -> list[dict[str, Any]]:
    """Raw network call: an address's recent transactions. Tests monkeypatch THIS."""
    url = f"{MEMPOOL_API_BASE}/address/{address}/txs"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    return data if isinstance(data, list) else []


async def _fetch_txs(address: str) -> list[dict[str, Any]]:
    """Cached wrapper over :func:`_http_get_txs` (short TTL, rate-limit courtesy)."""
    now = time.monotonic()
    hit = _cache.get(address)
    if hit is not None and hit[0] > now:
        return hit[1]
    txs = await _http_get_txs(address)
    _cache[address] = (now + _CACHE_TTL, txs)
    return txs


def _counterparties(address: str, txs: list[dict[str, Any]]) -> dict[str, set[str]]:
    """``counterparty_address -> {directions}`` derived from the txs. A counterparty
    can be both sent-to and received-from across different txs."""
    out: dict[str, set[str]] = {}
    for tx in txs:
        in_addrs: set[str] = {
            addr
            for vin in tx.get("vin", [])
            if (addr := (vin.get("prevout") or {}).get("scriptpubkey_address"))
        }
        out_addrs: set[str] = {
            addr for vout in tx.get("vout", []) if (addr := vout.get("scriptpubkey_address"))
        }
        if address in in_addrs:  # we spent -> we sent to every output address
            for b in out_addrs:
                if b != address:
                    out.setdefault(b, set()).add(SENT_TO)
        if address in out_addrs:  # we received -> from every input address
            for b in in_addrs:
                if b != address:
                    out.setdefault(b, set()).add(RECEIVED_FROM)
    return out


class MempoolConnectedWallets(RemoteEnrichment):
    """``btc_wallet -> connected wallets`` (sent_to / received_from) via mempool."""

    src_type = "artifact"
    name = "connected_wallets"
    output_type = "artifact"
    edge_kind = SENT_TO  # representative; real per-edge kinds are in the result

    async def _artifact(
        self, ctx: ExpandContext, src_id: UUID
    ) -> InfrastructureArtifactTable | None:
        row = (
            await ctx.session.exec(
                select(InfrastructureArtifactTable).where(InfrastructureArtifactTable.id == src_id)
            )
        ).first()
        return cast("InfrastructureArtifactTable | None", row)

    async def applicable(self, ctx: ExpandContext, src_id: UUID) -> bool:
        art = await self._artifact(ctx, src_id)
        return art is not None and art.kind == _BTC_KIND

    async def resolve_src_value(self, ctx: ExpandContext, src_id: UUID) -> str:
        art = await self._artifact(ctx, src_id)
        if art is None:
            raise ValueError(f"artifact {src_id} not found")
        if art.kind != _BTC_KIND:
            raise ValueError(f"artifact {src_id!r} is not a {_BTC_KIND}")
        return art.value

    async def fetch(
        self,
        ctx: ExpandContext,
        src_id: UUID,
        src_value: str,
        *,
        limit: int,
        offset: int,
        want_total: bool,
    ) -> ExpandResult:
        counterparties = _counterparties(src_value, await _fetch_txs(src_value))
        addresses = sorted(counterparties)  # deterministic paging
        total = len(addresses) if want_total else None
        page = addresses[offset : offset + limit]
        has_more = len(addresses) > offset + limit

        # Match this page against the corpus by value_hash, so known wallets link to
        # their existing graph node instead of a duplicate ephemeral one.
        existing: dict[str, InfrastructureArtifactTable] = {}
        if page:
            hashes = {a: _value_hash(a) for a in page}
            rows = await ctx.session.exec(
                select(InfrastructureArtifactTable).where(
                    col(InfrastructureArtifactTable.value_hash).in_(list(hashes.values()))
                )
            )
            by_hash = {r.value_hash: r for r in rows}
            existing = {a: by_hash[h] for a, h in hashes.items() if h in by_hash}

        nodes: list[ExpandNode] = []
        edges: list[dict[str, Any]] = []
        for address in page:
            row = existing.get(address)
            if row is not None:
                node = ExpandNode(
                    entity_type="artifact",
                    entity_id=row.id,
                    title=row.value,
                    status=None,
                    source_id=row.resolved_to_source_id,
                    fields={"kind": _BTC_KIND},
                )
            else:
                node = ExpandNode(
                    entity_type="artifact",
                    entity_id=_ephemeral_id(address),
                    title=address,
                    status=None,
                    source_id=None,
                    fields={"kind": _BTC_KIND, "ephemeral": True},
                )
            nodes.append(node)
            for direction in sorted(counterparties[address]):
                edges.append({"src_id": src_id, "dst_id": node.entity_id, "kind": direction})
        return ExpandResult(nodes=nodes, edges=edges, total=total, has_more=has_more)


__all__ = ["MempoolConnectedWallets"]
