# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/incidents handler — direct-call (ASGI handlers aren't coverage-traced)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eyenet.api.v1.incidents.api_list_incidents import list_incidents

pytestmark = pytest.mark.unit


class _FakeStorage:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    async def recent_incidents(self, limit: int) -> list:
        return self._rows[:limit]

    async def bodies_by_message_ids(self, message_ids: list) -> dict:
        return {mid: f"body {mid}" for mid in message_ids}

    async def incident_labels_by_message_ids(self, message_ids: list) -> dict:
        return {}


def _row(labels: list[str]):
    return SimpleNamespace(
        message_id=uuid4(),
        labels=labels,
        scores={"tooling": 0.9},
        model_version="mmbert-ml",
        classified_at=datetime.now(UTC),
    )


def test_list_incidents_maps_all() -> None:
    storage = _FakeStorage([_row(["tooling"]), _row(["leak"]), _row(["tooling", "leak"])])
    out = asyncio.run(list_incidents(_=None, storage=storage, limit=50, label=None))
    assert len(out) == 3
    assert out[0].scores == {"tooling": 0.9}
    assert all(o.body == f"body {o.message_id}" for o in out)  # body enrichment


def test_list_incidents_label_filter() -> None:
    storage = _FakeStorage([_row(["tooling"]), _row(["leak"]), _row(["tooling", "leak"])])
    out = asyncio.run(list_incidents(_=None, storage=storage, limit=50, label="tooling"))
    assert len(out) == 2
    assert all("tooling" in o.labels for o in out)
