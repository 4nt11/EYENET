# SPDX-License-Identifier: AGPL-3.0-or-later
"""Incident history backfill: the storage enumeration query + the backfill driver."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.incidents import backfill
from eyenet.incidents.classifier import HeadScore
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _records(n: int) -> list[dict]:
    return [
        {"actor_key": "a1", "platform_msgid": str(i), "body": f"msg {i}"} for i in range(n)
    ]


@pytest.mark.integration
def test_messages_without_incidents_skips_classified_and_keysets(storage) -> None:
    from eyenet.contracts.incident import IncidentRow
    from tests._seed import seed_telegram_fixture

    async def _run() -> None:
        now = datetime.now(UTC)
        await seed_telegram_fixture(storage, _records(3), now)

        page = await storage.messages_without_incidents(limit=10)
        assert len(page) == 3
        bodies = [b for _mid, b in page]
        assert bodies == ["msg 0", "msg 1", "msg 2"]  # oldest-first (UUID7 keyset)

        # classify the first message -> it drops out of the un-classified set
        first_id = page[0][0]
        await storage.put_incidents_bulk(
            [
                IncidentRow(
                    message_id=first_id,
                    labels=["incident"],
                    scores={"incident": 0.9},
                    model_version="test",
                    classified_at=now,
                )
            ]
        )
        remaining = await storage.messages_without_incidents(limit=10)
        assert [mid for mid, _ in remaining] == [page[1][0], page[2][0]]

        # keyset: after_id past the first remaining returns only the last
        tail = await storage.messages_without_incidents(limit=10, after_id=page[1][0])
        assert [mid for mid, _ in tail] == [page[2][0]]

    asyncio.run(_run())


@pytest.mark.integration
def test_recent_incidents_label_filter_finds_rare_regardless_of_recency(storage) -> None:
    from datetime import timedelta

    from eyenet.contracts.incident import IncidentRow

    async def _run() -> None:
        base = datetime.now(UTC)
        rows = []
        # one OLD rare 'alliance' incident, then many newer 'fraud_ops' ones on top of it
        rows.append(IncidentRow(message_id=UUID(int=1), labels=["alliance"], scores={},
                                model_version="v2", classified_at=base))
        for i in range(2, 12):
            rows.append(IncidentRow(message_id=UUID(int=i), labels=["fraud_ops"], scores={},
                                    model_version="v2", classified_at=base + timedelta(minutes=i)))
        await storage.put_incidents_bulk(rows)
        # recent 3 (no filter) are all fraud_ops — the old alliance one is buried
        top = await storage.recent_incidents(limit=3)
        assert all("fraud_ops" in r.labels for r in top)
        # but filtering by the rare label finds it despite being oldest (the bug fix)
        found = await storage.recent_incidents(limit=3, labels=["alliance"])
        assert len(found) == 1 and found[0].labels == ["alliance"]
        # multi-label OR: alliance OR fraud_ops returns both kinds
        multi = await storage.recent_incidents(limit=20, labels=["alliance", "fraud_ops"])
        assert len(multi) == 11
        assert any(r.labels == ["alliance"] for r in multi)
        # offset paging
        page2 = await storage.recent_incidents(limit=3, offset=3)
        assert len(page2) == 3

    asyncio.run(_run())


@pytest.mark.integration
def test_recent_incidents_group_filter_shows_only_selected(storage) -> None:
    from eyenet.contracts.incident import IncidentRow
    from tests._seed import seed_telegram_fixture

    async def _run() -> None:
        now = datetime.now(UTC)
        # two groups under one source; classify one message in each
        _s, g_a, _a = await seed_telegram_fixture(
            storage, [{"actor_key": "a", "platform_msgid": "1", "body": "spam"}], now,
            platform_groupid="-100", group_title="Alpha",
        )
        _s2, g_b, _b = await seed_telegram_fixture(
            storage, [{"actor_key": "a", "platform_msgid": "2", "body": "signal"}], now,
            platform_groupid="-200", group_title="Beta",
        )
        page = {b: mid for mid, b in await storage.messages_without_incidents(limit=10)}
        await storage.put_incidents_bulk([
            IncidentRow(message_id=page["spam"], labels=["x"], scores={},
                        model_version="v", classified_at=now),
            IncidentRow(message_id=page["signal"], labels=["x"], scores={},
                        model_version="v", classified_at=now),
        ])
        assert len(await storage.recent_incidents(limit=10)) == 2  # all by default
        only_b = await storage.recent_incidents(limit=10, group_ids=[g_b])
        assert {r.message_id for r in only_b} == {page["signal"]}  # show-only the chosen group

        # incident_groups lists BOTH groups (full set, window-independent) with counts
        groups = await storage.incident_groups()
        assert {gid for gid, _t, _n in groups} == {g_a, g_b}
        assert {t: n for _g, t, n in groups} == {"Alpha": 1, "Beta": 1}

    asyncio.run(_run())


@pytest.mark.integration
def test_incident_label_upsert_and_bulk(storage) -> None:
    from datetime import datetime as _dt

    async def _run() -> None:
        mid = UUID(int=42)
        now = _dt.now(UTC)
        r1 = await storage.set_incident_label(
            mid, ["leak"], decided_by="op", reason="a", decided_at=now
        )
        assert r1.labels == ["leak"]
        # upsert: second call replaces, one row per message
        r2 = await storage.set_incident_label(
            mid, ["incident"], decided_by="op2", reason="b", decided_at=now
        )
        assert r2.labels == ["incident"] and r2.decided_by == "op2"
        got = await storage.incident_labels_by_message_ids([mid, UUID(int=99)])
        assert set(got) == {mid} and got[mid].labels == ["incident"]  # unknown omitted
        assert len(await storage.all_incident_labels()) == 1  # still one row

    asyncio.run(_run())


class _FakeStorage:
    """In-list message store honoring the keyset contract run_backfill relies on."""

    def __init__(self, msgs: list[tuple[UUID, str]]) -> None:
        self._msgs = msgs
        self.saved: list = []

    async def list_incident_rules(self, *, enabled_only: bool = False):
        return []

    async def messages_without_incidents(self, *, limit=500, after_id=None):
        classified = {r.message_id for r in self.saved}
        out = [
            (mid, body)
            for mid, body in self._msgs
            if mid not in classified and (after_id is None or mid > after_id)
        ]
        return out[:limit]

    async def attachment_files_by_message_ids(self, message_ids):
        return {}

    async def put_incidents_bulk(self, rows) -> None:
        self.saved.extend(rows)


@pytest.mark.unit
def test_run_backfill_stores_fired_skips_nonfiring_and_terminates(monkeypatch) -> None:
    # UUIDs must be ordered for the keyset walk over non-firing messages.
    msgs = [(UUID(int=i), f"body {i}") for i in range(1, 6)]
    # fake model: only bodies containing "hit" fire; the prefilter/rules add nothing.
    msgs[1] = (msgs[1][0], "hit one")
    msgs[3] = (msgs[3][0], "hit two")
    monkeypatch.setattr(
        backfill.classifier,
        "classify_batch",
        lambda texts: [
            [HeadScore("incident", 0.9, "hit" in t), HeadScore("leak", 0.01, False)] for t in texts
        ],
    )
    monkeypatch.setattr(backfill.classifier, "prefilter_labels", lambda t: set())
    monkeypatch.setattr(backfill.rules, "match_labels", lambda t, c: set())

    storage = _FakeStorage(msgs)
    scanned, fired = asyncio.run(backfill.run_backfill(storage, batch_size=2))

    assert scanned == 5  # every message walked exactly once (keyset advanced past non-firing)
    assert fired == 2
    assert {r.labels[0] for r in storage.saved} == {"incident"}
