# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/incidents handler — direct-call (ASGI handlers aren't coverage-traced)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.incidents.api_list_incidents import (
    list_incident_countries,
    list_incident_groups,
    list_incidents,
)

pytestmark = pytest.mark.unit


def _page(*, limit: int = 50, offset: int = 0, include_total: bool = False) -> CursorParams:
    return CursorParams(offset=offset, limit=limit, include_total=include_total)


class _FakeStorage:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def _filter(self, labels, group_ids) -> list:
        rows = self._rows
        if labels:
            rows = [r for r in rows if any(lbl in r.labels for lbl in labels)]
        if group_ids:
            rows = [r for r in rows if r.group_id in group_ids]
        return rows

    async def recent_incidents(
        self,
        limit: int,
        *,
        labels=None,
        offset: int = 0,
        q=None,
        group_ids=None,
        source_ids=None,
        victim_countries=None,
        exclude_bodyless: bool = False,
    ) -> list:
        # q/FTS + exclude_bodyless + victim_countries semantics are covered at the
        # storage layer (test_incident_search_sqlite / test_backfill); this fake
        # exercises response mapping + the label(OR)/group-filter + paging math.
        return self._filter(labels, group_ids)[offset : offset + limit]

    async def count_incidents(
        self,
        *,
        labels=None,
        q=None,
        group_ids=None,
        source_ids=None,
        victim_countries=None,
        exclude_bodyless: bool = False,
    ) -> int:
        return len(self._filter(labels, group_ids))

    async def incident_countries(self) -> list:
        return [("CL", 12), ("AR", 4)]

    async def bodies_by_message_ids(self, message_ids: list) -> dict:
        return {mid: f"body {mid}" for mid in message_ids}

    async def incident_labels_by_message_ids(self, message_ids: list) -> dict:
        return {}

    async def message_geo_by_message_ids(self, message_ids: list) -> dict:
        # first message gets a CL verdict; the rest are un-attributed (None country)
        return (
            {
                message_ids[0]: SimpleNamespace(
                    country="CL", status="resolved", decided_by="country_name"
                )
            }
            if message_ids
            else {}
        )

    async def message_context_by_ids(self, message_ids: list) -> dict:
        # fields returned: group_title, group_id, actor_id, actor_handle
        return {mid: ("Cash Network", uuid4(), uuid4(), "@scammer") for mid in message_ids}

    async def incident_groups(self) -> list:
        return [(uuid4(), "Noisy Market", uuid4(), 42), (uuid4(), "Quiet Chan", uuid4(), 3)]


def _row(labels: list[str], group_id=None):
    return SimpleNamespace(
        message_id=uuid4(),
        group_id=group_id or uuid4(),
        labels=labels,
        scores={"tooling": 0.9},
        model_version="mmbert-ml",
        classified_at=datetime.now(UTC),
    )


def test_list_incidents_maps_all() -> None:
    storage = _FakeStorage([_row(["tooling"]), _row(["leak"]), _row(["tooling", "leak"])])
    page = asyncio.run(list_incidents(_=None, storage=storage, page=_page(), label=None))
    out = page.items
    assert len(out) == 3
    assert page.next_cursor is None  # whole set fit on the page
    assert page.estimated_total is None  # not requested
    assert out[0].scores == {"tooling": 0.9}
    assert all(o.body == f"body {o.message_id}" for o in out)  # body enrichment
    assert out[0].group == "Cash Network" and out[0].actor_handle == "@scammer"  # who/where
    assert out[0].group_id is not None  # group id surfaced for the group filter
    assert out[0].victim_country == "CL"  # geo verdict merged in
    assert out[1].victim_country is None  # un-attributed message stays None


def test_list_incidents_label_filter_multi() -> None:
    storage = _FakeStorage([_row(["tooling"]), _row(["leak"]), _row(["access_sale"])])
    # multi-select OR: tooling or leak (not access_sale)
    page = asyncio.run(
        list_incidents(_=None, storage=storage, page=_page(), label=["tooling", "leak"])
    )
    assert len(page.items) == 2
    assert all(set(o.labels) & {"tooling", "leak"} for o in page.items)


def test_list_incidents_group_filter() -> None:
    keep = uuid4()
    storage = _FakeStorage([_row(["tooling"], group_id=keep), _row(["leak"])])
    page = asyncio.run(
        list_incidents(_=None, storage=storage, page=_page(), label=None, group_id=[keep])
    )
    assert len(page.items) == 1 and page.items[0].labels == ["tooling"]  # only the chosen group


def test_list_incidents_paginates_with_cursor_and_total() -> None:
    storage = _FakeStorage([_row(["a"]), _row(["b"]), _row(["c"])])
    page = asyncio.run(
        list_incidents(_=None, storage=storage, page=_page(limit=2, include_total=True), label=None)
    )
    assert len(page.items) == 2  # capped to the requested page size
    assert page.next_cursor is not None  # a further page exists (over-fetch saw row 3)
    assert page.estimated_total == 3  # full match count, not just the page


def test_list_incidents_offset_pages() -> None:
    storage = _FakeStorage([_row(["a"]), _row(["b"]), _row(["c"])])
    page = asyncio.run(list_incidents(_=None, storage=storage, page=_page(offset=1), label=None))
    assert len(page.items) == 2  # first row skipped by offset


def test_list_incident_groups() -> None:
    storage = _FakeStorage([])
    out = asyncio.run(list_incident_groups(_=None, storage=storage))
    assert [g.title for g in out] == ["Noisy Market", "Quiet Chan"]  # noisiest first
    assert out[0].count == 42 and out[0].group_id is not None


def test_list_incident_countries() -> None:
    storage = _FakeStorage([])
    out = asyncio.run(list_incident_countries(_=None, storage=storage))
    assert [(c.country, c.count) for c in out] == [("CL", 12), ("AR", 4)]  # noisiest first
