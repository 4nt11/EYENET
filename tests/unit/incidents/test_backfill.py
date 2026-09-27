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
