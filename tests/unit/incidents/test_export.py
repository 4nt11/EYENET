# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operator-correction export -> gold JSONL the ML trainer consumes."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest

from eyenet.incidents.export import export_operator_labels
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.mark.integration
def test_export_shape_matches_trainer_gold(storage, tmp_path) -> None:
    from tests._seed import seed_telegram_fixture

    async def _run() -> None:
        now = datetime.now(UTC)
        recs = [
            {"actor_key": "a1", "platform_msgid": "1", "body": "selling rdp access"},
            {"actor_key": "a1", "platform_msgid": "2", "body": "gm frens"},
        ]
        await seed_telegram_fixture(storage, recs, now)
        page = await storage.messages_without_incidents(limit=10)
        by_body = {b: mid for mid, b in page}

        await storage.set_incident_label(
            by_body["selling rdp access"], ["access_sale"],
            decided_by="op", reason="Incorrectly tagged", decided_at=now,
        )
        await storage.set_incident_label(
            by_body["gm frens"], [],  # false positive
            decided_by="op", reason="False positive", decided_at=now,
        )

        out = tmp_path / "operator_corrections.mllabels.jsonl"
        n = await export_operator_labels(storage, out)
        assert n == 2

        rows = [json.loads(x) for x in out.read_text().splitlines() if x.strip()]
        by_text = {r["text"]: r for r in rows}
        # trainer's label_vec reads {"text","labels":[...]}; empty list = all-zeros negative
        assert by_text["selling rdp access"]["labels"] == ["access_sale"]
        assert by_text["gm frens"]["labels"] == []
        assert all("text" in r and isinstance(r["labels"], list) for r in rows)

    asyncio.run(_run())


@pytest.mark.integration
def test_export_empty_writes_empty_file(storage, tmp_path) -> None:
    async def _run() -> None:
        out = tmp_path / "x.mllabels.jsonl"
        assert await export_operator_labels(storage, out) == 0
        assert out.read_text() == ""

    asyncio.run(_run())
