# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for ``StealerArtifactsReader`` (v1.3.3 + v1.3.4).

``_rows`` is stubbed per-test with a recorder so we assert SQL
composition (filter wiring, WHERE assembly, parameters) plus dataclass
mapping, without touching ClickHouse.
"""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from eyenet.stealer.query import StealerArtifactsReader

pytestmark = pytest.mark.unit

_SHA = "a" * 64


class _Reader(StealerArtifactsReader):
    """Avoid the parent ``__init__``'s clickhouse_db() lookup during tests."""

    def __init__(self) -> None:
        self._db = "stealer"
        self._client = None
        self._calls: list[tuple[str, dict[str, object]]] = []
        self._responses: list[list[tuple[object, ...]]] = []

    def set_responses(self, rows: Iterable[list[tuple[object, ...]]]) -> None:
        self._responses = list(rows)

    def _rows(self, sql: str, params: dict[str, object]) -> list[tuple[object, ...]]:
        self._calls.append((sql, params))
        return self._responses.pop(0) if self._responses else []


def test_list_cards_filters_and_pagination() -> None:
    r = _Reader()
    card_row = (
        _SHA,
        "v-01",
        "US",
        "aff-42",
        "1.0",
        17,
        203,
        1,
        1,
        1,
        0,
    )
    r.set_responses([[(2,)], [card_row, card_row]])

    rows, total, pages = r.list_cards(
        page=2,
        limit=25,
        country="US",
        traffic_affid="aff-42",
        has_wallet=True,
        has_corporate=True,
    )
    assert total == 2
    assert pages == 1
    assert len(rows) == 2
    assert rows[0].victim_folder == "v-01"
    assert rows[0].has_wallet is True

    count_sql, count_params = r._calls[0]
    assert "count()" in count_sql
    assert count_params["country"] == "US"
    assert count_params["affid"] == "aff-42"
    assert count_params["hw"] == 1
    assert count_params["hc"] == 1

    list_sql, list_params = r._calls[1]
    assert "LIMIT {limit:UInt32} OFFSET {offset:UInt32}" in list_sql
    assert list_params["offset"] == 25  # page 2, limit 25


def test_list_cards_no_filters() -> None:
    r = _Reader()
    r.set_responses([[(0,)], []])
    rows, total, pages = r.list_cards(page=1, limit=10)
    assert rows == []
    assert total == 0
    assert pages == 0


def test_detail_returns_none_when_no_row() -> None:
    r = _Reader()
    r.set_responses([[]])
    assert r.detail(_SHA, "v-01") is None


def test_detail_hydrates_full_row_with_ttps_and_hits() -> None:
    r = _Reader()
    detail_row = (
        "khazan",
        "US",
        "192.0.2.1",  # pragma: allowlist secret
        "alice",
        "DESK",
        "win10",
        "aff-42",
        "1.0",
        "d" * 32,
        "C:\\",
        17,
        203,
        5,
        100,
        4,
        200,
        80,
        1,
        0,
        1,
        2,
        1,
        1,
        0,
        1,
        0,
        "",
        "acme.com",
        "metamask",
    )
    r.set_responses(
        [
            [detail_row],
            [("passwords_block_title",), ("cookies_netscape_tsv",)],
            [(7,)],  # monitored-domain hits
        ]
    )
    out = r.detail(_SHA, "v-01")
    assert out is not None
    assert out.source == "khazan"
    assert out.creds_count == 17
    assert out.fired_rule_ids == ["passwords_block_title", "cookies_netscape_tsv"]
    assert out.monitored_domain_hits == 7


def test_monitored_domain_hits_zero_when_watchlist_empty() -> None:
    r = _Reader()
    r.set_responses([[(0,)]])
    assert r._monitored_domain_hits(_SHA, "v-01") == 0
    sql, _params = r._calls[0]
    assert "monitored_domains" in sql
    assert "match_type = 'exact'" in sql
    assert "match_type = 'suffix'" in sql


def test_file_tree_maps_rows() -> None:
    r = _Reader()
    r.set_responses(
        [
            [
                ("v-01/P.txt", "P.txt", 2048, "passwords", 1, 17, "head", "f" * 64),
            ]
        ]
    )
    rows = r.file_tree(_SHA, "v-01")
    assert rows[0].filename == "P.txt"
    assert rows[0].size_bytes == 2048
    assert rows[0].extractor_touched is True


def test_records_filters_by_rule_and_family() -> None:
    r = _Reader()
    rec_row = ("passwords_block_title", "khazan", "arch/v-01/P.txt", {"u": "a"})
    r.set_responses([[(1,)], [rec_row]])
    rows, total, pages = r.records(
        _SHA, "v-01", page=1, limit=50, rule_id="passwords_block_title", family="khazan"
    )
    assert total == 1
    assert pages == 1
    assert rows[0].fields == {"u": "a"}
    _count_sql, count_params = r._calls[0]
    assert count_params["rid"] == "passwords_block_title"
    assert count_params["fam"] == "khazan"


def test_records_tolerates_null_fields_dict() -> None:
    r = _Reader()
    r.set_responses([[(1,)], [("r", "f", "p", None)]])
    rows, _total, _pages = r.records(_SHA, "v-01", page=1, limit=50)
    assert rows[0].fields == {}


def test_domains_maps_rows() -> None:
    r = _Reader()
    r.set_responses(
        [
            [
                ("accounts.google.com", "credential", 4),
                ("facebook.com", "cookie", 12),
            ]
        ]
    )
    rows = r.domains(_SHA, "v-01")
    assert [d.domain for d in rows] == ["accounts.google.com", "facebook.com"]
    assert rows[1].count == 12


def test_page_count_rounds_up() -> None:
    assert StealerArtifactsReader._page_count(0, 10) == 0
    assert StealerArtifactsReader._page_count(10, 10) == 1
    assert StealerArtifactsReader._page_count(11, 10) == 2
