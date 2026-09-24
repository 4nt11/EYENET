# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared-infrastructure linker: extraction + pure edge ranking + batch runner."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts.enums import GroupKind, LinkageState, SourceKind
from eyenet.linker.indicators import extract_indicators
from eyenet.linker.infra_linker import propose_infra_edges, run_infra_linker
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

A = UUID("00000000-0000-0000-0000-0000000000a1")
B = UUID("00000000-0000-0000-0000-0000000000b2")
C = UUID("00000000-0000-0000-0000-0000000000c3")
D = UUID("00000000-0000-0000-0000-0000000000d4")


@pytest.mark.unit
def test_extract_indicators_kinds_and_normalization() -> None:
    text = (
        "Contact @WBpay_MM1888 or t.me/WBpay_wh — pay TRX "
        "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t or 0xAbCdef0123456789abcdef0123456789ABCDEF01"
    )
    got = extract_indicators(text)
    assert "handle:wbpay_mm1888" in got  # case-folded
    assert "tme:wbpay_wh" in got
    assert "wallet_trx:TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t" in got  # case preserved
    assert "wallet_evm:0xabcdef0123456789abcdef0123456789abcdef01" in got  # folded


@pytest.mark.unit
def test_extract_indicators_stoplist_and_empty() -> None:
    assert extract_indicators("ping @admin @everyone") == set()  # ambient handles dropped
    assert extract_indicators(None) == set()
    assert extract_indicators("just prose, no infra") == set()


@pytest.mark.unit
def test_propose_edges_separates_crews() -> None:
    # Two crews. WBpay: A,B share a rare handle. LV: C,D share a different one.
    # An ambient handle (@promo) is in everyone -> must NOT link the crews.
    ambient = {f"handle:promo{i}" for i in range(0)}  # placeholder, see below
    actor_indicators = {
        A: {"handle:wbpay_mm1888", "handle:ambient"},
        B: {"handle:wbpay_mm1888", "handle:ambient"},
        C: {"handle:lv000098", "handle:ambient"},
        D: {"handle:lv000098", "handle:ambient"},
    }
    assert ambient == set()
    # @ambient is carried by all 4 -> df=4; cap it out so it can't bridge crews.
    edges = propose_infra_edges(actor_indicators, max_df=2, weight_floor=0.1)
    pairs = {(e.actor_a, e.actor_b) for e in edges}
    assert (A, B) in pairs  # WBpay crew linked
    assert (C, D) in pairs  # LV crew linked
    # No cross-crew edge (they only shared the capped-out ambient handle).
    assert (A, C) not in pairs and (A, D) not in pairs and (B, C) not in pairs


@pytest.mark.unit
def test_propose_edges_rare_shared_scores_higher() -> None:
    actor_indicators = {
        A: {"handle:rare_wallet_desk", "handle:common"},
        B: {"handle:rare_wallet_desk", "handle:common"},
        C: {"handle:common"},
        D: {"handle:common"},  # keeps df(common) high -> low IDF
    }
    edges = propose_infra_edges(actor_indicators, max_df=4, weight_floor=0.0)
    ab = next(e for e in edges if {e.actor_a, e.actor_b} == {A, B})
    assert "handle:rare_wallet_desk" in ab.shared
    assert ab.score > 0.5  # dominated by the rare shared handle


@pytest.mark.unit
async def test_run_infra_linker_persists_shared_infra_linkages() -> None:
    storage: BaseRepository = get_repository(in_memory=True)
    now = datetime.now(tz=UTC)
    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=now)

    gid = await storage.upsert_group(
        source_id=src, platform_groupid="@g", kind=GroupKind.CHANNEL, title="g", seen_at=now
    )
    counter = 0

    async def _actor(body: str) -> UUID:
        nonlocal counter
        counter += 1
        uid = str(10**7 + counter)
        a = await storage.upsert_actor(
            source_id=src,
            actor_key=f"actor:tg:{uid}",
            platform_userid=uid,
            handle=None,
            display_name=f"bot{counter}",
            seen_at=now,
        )
        await storage.put_message(_mk_message(a, gid, src, body, now, counter), None)
        return a

    # Two accounts share @wbpay_desk; a third is unrelated.
    a1 = await _actor("we need USDT contact @wbpay_desk t.me/x")
    a2 = await _actor("USDT here @wbpay_desk long term")
    await _actor("unrelated chatter, no infra at all")

    n = await run_infra_linker(storage, max_df=10, weight_floor=0.1)
    assert n >= 1
    links = await storage.list_linkages(state=LinkageState.PROPOSED)
    infra = [x for x in links if x.method == "shared_infra"]
    assert infra, "expected a shared_infra linkage"
    linked = {frozenset((x.actor_a_id, x.actor_b_id)) for x in infra}
    assert frozenset((a1, a2)) in linked


def _mk_message(actor_id, group_id, source_id, body, now, n):
    from eyenet.models import MessageTable
    from eyenet.models._base import new_uuid7

    return MessageTable(
        id=new_uuid7(),
        source_id=source_id,
        group_id=group_id,
        actor_id=actor_id,
        platform_msgid=f"m{n}",
        evidence_ref=f"telegram:g:{n}",
        body=body,
        length_chars=len(body),
        length_words=len(body.split()),
        sent_at_source=now,
        ingested_at=now,
    )
