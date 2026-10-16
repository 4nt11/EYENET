#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Live smoke for the mempool BTC enrichment (ANTI runs this; it hits the REAL API).

Pulls an address's recent transactions from the configured mempool API
(``EYENET_MEMPOOL_API_BASE``, default https://mempool.space/api) and prints the
connected wallets with their direction(s) - exactly what the
``connected_wallets`` enrichment derives, minus the DB dedup (no repo needed).

Usage:
    .venv/bin/python development/scripts/mempool_smoke.py <btc_address> [limit]

OPSEC: this reveals the queried address to the API host. Set
EYENET_MEMPOOL_API_BASE to a self-hosted / .onion mempool for real investigations.
"""

from __future__ import annotations

import asyncio
import sys

from eyenet.enrichments.remote import mempool_btc


async def _main() -> int:
    args = sys.argv[1:]
    if not args:
        print("usage: mempool_smoke.py <btc_address> [limit]")
        return 2
    address = args[0]
    limit = int(args[1]) if len(args) > 1 else 25
    print(f"API : {mempool_btc.MEMPOOL_API_BASE}")
    print(f"addr: {address}")
    txs = await mempool_btc._http_get_txs(address)
    print(f"fetched {len(txs)} transactions")
    counterparties = mempool_btc._counterparties(address, txs)
    print(f"{len(counterparties)} connected wallets (showing up to {limit}):")
    for addr in sorted(counterparties)[:limit]:
        directions = "/".join(sorted(counterparties[addr]))
        print(f"  {directions:24s} {addr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
