# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call tests for the read:stealer query handlers (stats + search).

The ClickHouse reader is stubbed — this covers response mapping + the 503-when-the-
corpus-is-down path, not the SQL (that's integration against a live ClickHouse)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from eyenet.api.deps import CurrentUser
from eyenet.api.v1.stealer import api_stealer_search as search_mod, api_stealer_stats as stats_mod
from eyenet.contracts.enums import SystemUserRole
from eyenet.stealer.query import Bucket, CredRow, StealerStats

pytestmark = pytest.mark.unit


def _user() -> CurrentUser:
    return CurrentUser(
        user_id=uuid4(),
        username="op",
        role=SystemUserRole.ANALYST,
        effective_scopes=frozenset({"read:stealer"}),
        token_expires_at=None,
    )


async def test_stats_maps_reader_output(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = StealerStats(
        total_creds=110001,
        unique_creds=53341,
        distinct_hosts=9001,
        by_scheme=[Bucket("https", 59939), Bucket("android", 8646)],
        by_tld=[Bucket("com", 40000), Bucket("ru", 1200)],
        top_hosts=[Bucket("accounts.google.com", 2744)],
    )
    monkeypatch.setattr(stats_mod._reader, "stats", lambda **_k: fake)
    resp = await stats_mod.stealer_stats(_user())
    assert resp.total_creds == 110001
    assert resp.unique_creds == 53341
    assert [b.key for b in resp.by_scheme] == ["https", "android"]
    assert resp.top_hosts[0].count == 2744


async def test_stats_503_when_corpus_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(**_k: object) -> StealerStats:
        raise ConnectionError("clickhouse down")

    monkeypatch.setattr(stats_mod._reader, "stats", _boom)
    with pytest.raises(HTTPException) as ei:
        await stats_mod.stealer_stats(_user())
    assert ei.value.status_code == 503


async def test_search_maps_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        CredRow("accounts.google.com", "https://...", "u@x.com", "pw", "https", "com"),
        CredRow("m.facebook.com", "m.facebook.com/", "0171", "pw2", "https", "com"),
    ]
    monkeypatch.setattr(search_mod._reader, "search", lambda **_k: rows)
    resp = await search_mod.stealer_search(_user(), host="google", limit=100, offset=0)
    assert [c.host for c in resp.items] == ["accounts.google.com", "m.facebook.com"]
    assert resp.items[0].password == "pw"


async def test_search_503_when_corpus_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(**_k: object) -> list[CredRow]:
        raise ConnectionError("clickhouse down")

    monkeypatch.setattr(search_mod._reader, "search", _boom)
    with pytest.raises(HTTPException) as ei:
        await search_mod.stealer_search(_user(), host=None, limit=100, offset=0)
    assert ei.value.status_code == 503
