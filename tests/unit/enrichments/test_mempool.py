# SPDX-License-Identifier: AGPL-3.0-or-later
"""MempoolConnectedWallets remote enrichment (mocked HTTP, no network).

Exercises the btc_wallet -> connected wallets pivot through storage.graph_expand:
directional edges, real-vs-ephemeral node resolution, applicability by kind, and the
None degree count for a remote enrichment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from eyenet.enrichments.remote import mempool_btc
from eyenet.enrichments.remote.mempool_btc import _ephemeral_id, _value_hash
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 5, tzinfo=UTC)

_A = "A_addr"  # the source wallet
_B = "B_addr"  # new counterparty (we sent to it) -> ephemeral
_C = "C_addr"  # known counterparty (it paid us) -> real DB node

# A spends to B (tx1); C spends to A (tx2).
_TXS: list[dict[str, Any]] = [
    {"vin": [{"prevout": {"scriptpubkey_address": _A}}], "vout": [{"scriptpubkey_address": _B}]},
    {"vin": [{"prevout": {"scriptpubkey_address": _C}}], "vout": [{"scriptpubkey_address": _A}]},
]


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.fixture(autouse=True)
def _mock_http(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(address: str) -> list[dict[str, Any]]:
        return _TXS

    mempool_btc._clear_cache()
    monkeypatch.setattr(mempool_btc, "_http_get_txs", _fake)


async def _seed(storage: BaseRepository) -> tuple[Any, Any]:
    ids = await storage.put_infrastructure_artifacts_bulk(
        [("wallet_btc", _A, _NOW, _NOW), ("wallet_btc", _C, _NOW, _NOW)]
    )
    return ids[_value_hash(_A)], ids[_value_hash(_C)]


async def test_connected_wallets_directional_and_dedup(storage: BaseRepository) -> None:
    a_id, c_id = await _seed(storage)
    nodes, edges, total, more = await storage.graph_expand(
        src_type="artifact",
        src_id=a_id,
        enrichment="connected_wallets",
        limit=10,
        offset=0,
        want_total=True,
    )
    by_id = {n.entity_id: n for n in nodes}
    # B is new -> ephemeral uuid5 node; C is in the corpus -> its real id
    assert set(by_id) == {_ephemeral_id(_B), c_id}
    assert by_id[_ephemeral_id(_B)].fields.get("ephemeral") is True
    assert "ephemeral" not in by_id[c_id].fields
    # directional edges from the source wallet
    assert {(e["dst_id"], e["kind"]) for e in edges} == {
        (_ephemeral_id(_B), "sent_to"),
        (c_id, "received_from"),
    }
    assert all(e["src_id"] == a_id for e in edges)
    assert total == 2
    assert more is False
    await storage.close()


async def test_counts_lists_remote_with_null_and_skips_non_btc(storage: BaseRepository) -> None:
    a_id, _c_id = await _seed(storage)
    counts = await storage.graph_expand_counts(src_type="artifact", src_id=a_id)
    # remote enrichment is advertised but has no cheap count
    assert counts["connected_wallets"] is None
    assert counts["messages"] == 0  # local enrichment, real int
    # a non-btc artifact must NOT offer the mempool enrichment
    onion = (await storage.put_infrastructure_artifacts_bulk([("onion", "x.onion", _NOW, _NOW)]))[
        _value_hash("x.onion")
    ]
    onion_counts = await storage.graph_expand_counts(src_type="artifact", src_id=onion)
    assert "connected_wallets" not in onion_counts
    await storage.close()


async def test_expand_non_btc_is_rejected(storage: BaseRepository) -> None:
    onion = (await storage.put_infrastructure_artifacts_bulk([("onion", "y.onion", _NOW, _NOW)]))[
        _value_hash("y.onion")
    ]
    with pytest.raises(ValueError, match="not a wallet_btc"):
        await storage.graph_expand(
            src_type="artifact",
            src_id=onion,
            enrichment="connected_wallets",
            limit=10,
            offset=0,
            want_total=False,
        )
    await storage.close()
