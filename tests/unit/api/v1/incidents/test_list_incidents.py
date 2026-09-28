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

    async def recent_incidents(self, limit: int, *, label=None, offset: int = 0) -> list:
        rows = self._rows if label is None else [r for r in self._rows if label in r.labels]
        return rows[offset : offset + limit]

    async def bodies_by_message_ids(self, message_ids: list) -> dict:
        return {mid: f"body {mid}" for mid in message_ids}

    async def incident_labels_by_message_ids(self, message_ids: list) -> dict:
        return {}

    async def message_context_by_ids(self, message_ids: list) -> dict:
        return {mid: ("Cash Network", uuid4(), "@scammer") for mid in message_ids}


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
    assert out[0].group == "Cash Network" and out[0].actor_handle == "@scammer"  # who/where


def test_list_incidents_label_filter() -> None:
    storage = _FakeStorage([_row(["tooling"]), _row(["leak"]), _row(["tooling", "leak"])])
    out = asyncio.run(list_incidents(_=None, storage=storage, limit=50, offset=0, label="tooling"))
    assert len(out) == 2
    assert all("tooling" in o.labels for o in out)


def test_list_incidents_offset_pages() -> None:
    storage = _FakeStorage([_row(["a"]), _row(["b"]), _row(["c"])])
    out = asyncio.run(list_incidents(_=None, storage=storage, limit=50, offset=1, label=None))
    assert len(out) == 2  # first row skipped by offset
