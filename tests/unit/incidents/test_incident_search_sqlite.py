# SPDX-License-Identifier: AGPL-3.0-or-later
"""Incident triage free-text search (``recent_incidents(q=...)``).

The ``q`` surface is generic (LIKE fallback works on any backend); this probe pins the
SQLite backend because it also asserts FTS5-specific behaviour — sync-trigger freshness
after a body edit, and phrase-escaping neutralising a MATCH operator (§2.3 Rule 2).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> BaseRepository:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    return get_repository(data_dir=tmp_path)


def _records() -> list[dict]:
    return [
        {"actor_key": "a1", "platform_msgid": "1", "body": "selling bulk sms gateway cheap"},
        {"actor_key": "a1", "platform_msgid": "2", "body": "HACKED BY crew greetz to all"},
        {"actor_key": "a1", "platform_msgid": "3", "body": "fresh database dump for sale"},
    ]


@pytest.mark.integration
def test_recent_incidents_q_searches_body(storage: BaseRepository) -> None:
    from eyenet.contracts.incident import IncidentRow
    from tests._seed import seed_telegram_fixture

    async def _run() -> None:
        now = datetime.now(UTC)
        await seed_telegram_fixture(storage, _records(), now)
        msgs = await storage.messages_without_incidents(limit=10)  # [(id, body), ...]
        # classify every message so it appears on the triage feed
        await storage.put_incidents_bulk(
            [
                IncidentRow(
                    message_id=mid,
                    labels=["incident"],
                    scores={"incident": 0.9},
                    model_version="test",
                    classified_at=now,
                )
                for mid, _body in msgs
            ]
        )

        async def bodies(**kw: object) -> list[str]:
            rows = await storage.recent_incidents(**kw)  # type: ignore[arg-type]
            ctx = await storage.bodies_by_message_ids([r.message_id for r in rows])  # type: ignore[attr-defined]
            return [ctx[r.message_id] for r in rows]

        # phrase match hits one body, filters the rest
        assert await bodies(q="bulk sms") == ["selling bulk sms gateway cheap"]
        # a term absent from every body returns nothing
        assert await bodies(q="ransomware") == []
        # composes with label (matching body + non-matching label -> empty)
        assert await bodies(q="greetz", label="not_a_real_label") == []

        # FTS5 sync trigger: editing the body re-indexes it
        first_id = msgs[0][0]
        async with storage.session() as s:  # type: ignore[attr-defined]
            from sqlalchemy import text

            await s.exec(
                text("UPDATE message SET body='pivoted to phishing kits' WHERE id=:i").bindparams(
                    i=str(first_id)
                )
            )
            await s.commit()
        assert await bodies(q="bulk sms") == []  # stale term gone
        assert await bodies(q="phishing") == ["pivoted to phishing kits"]  # new term indexed

        # phrase-escaping: a bare MATCH operator is treated as literal text, never a syntax
        # error (would raise if q leaked into FTS5 unquoted)
        assert await bodies(q="OR") == []

    asyncio.run(_run())
