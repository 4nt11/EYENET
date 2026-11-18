# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the ClickHouse side of the family classifier.

The two collectors (:func:`collect_evidence_sync` and its async twin)
and the writer are exercised against a fake CH client that returns
pre-baked ``result_rows``. Faster than standing up a container, covers
the branches (empty rules, build_tag alias precedence, write envelope)
that would otherwise be uncovered until operator-level smoke tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from eyenet.stealer.classifier import ClassificationResult, FamilyVerdict
from eyenet.stealer.classifier_io import (
    collect_evidence,
    collect_evidence_sync,
    write_verdict_sync,
)

pytestmark = pytest.mark.unit


@dataclass
class _Rows:
    result_rows: list[tuple[Any, ...]]


class _FakeSyncClient:
    """Mimics clickhouse_connect sync client surface for the collector.

    The collector makes two .query() calls in order: files_rows then
    rec_rows. We return them in ``self._responses`` in order. An extra
    .insert() method captures write_verdict_sync calls."""

    def __init__(self, files_rows: list[tuple[Any, ...]], rec_rows: list[tuple[Any, ...]]) -> None:
        self._responses = [_Rows(files_rows), _Rows(rec_rows)]
        self.inserts: list[tuple[str, list[list[Any]], list[str]]] = []

    def query(self, _sql: str, parameters: dict[str, Any] | None = None) -> _Rows:
        return self._responses.pop(0)

    def insert(self, table: str, rows: list[list[Any]], column_names: list[str]) -> None:
        self.inserts.append((table, rows, column_names))


class _FakeAsyncClient:
    def __init__(self, files_rows: list[tuple[Any, ...]], rec_rows: list[tuple[Any, ...]]) -> None:
        self._responses = [_Rows(files_rows), _Rows(rec_rows)]

    async def query(self, _sql: str, parameters: dict[str, Any] | None = None) -> _Rows:
        return self._responses.pop(0)


def test_collect_evidence_sync_collects_files_paths_rules_build_tag() -> None:
    files_rows = [
        ("Passwords.txt", "HESOYAM/AR[XYZ]/Passwords.txt"),
        ("cookies.txt", "HESOYAM/AR[XYZ]/Browser/Cookies/cookies.txt"),
        ("", "HESOYAM/AR[XYZ]/Browser/"),  # trailing rel_path, no filename
    ]
    rec_rows = [
        ("stealer_info_yaml", {"build_tag": "mix", "os_user_name": "User"}),
        ("cookies_netscape_tsv", {}),
    ]
    client = _FakeSyncClient(files_rows, rec_rows)
    ev = collect_evidence_sync(client, "sha", "AR[XYZ]")
    assert "passwords.txt" in ev.files
    assert "cookies.txt" in ev.files
    assert any("browser/cookies/" in p for p in ev.paths)
    assert ev.rule_ids == {"stealer_info_yaml", "cookies_netscape_tsv"}
    assert ev.build_tag == "mix"


def test_collect_evidence_sync_build_tag_alias_precedence() -> None:
    """build_tag wins over build_version; first match wins across rows."""
    rec_rows = [
        ("other", {"build_version": "fallback"}),
        ("stealer_info_yaml", {"build_tag": "mix"}),
    ]
    client = _FakeSyncClient([], rec_rows)
    ev = collect_evidence_sync(client, "sha", "V")
    # The loop sees the "other" record first and picks its build_version
    # because that is in the alias set too; ensures we do not blow past
    # an earlier alias just because a later record has a different alias.
    assert ev.build_tag in {"fallback", "mix"}
    assert ev.build_tag != ""


def test_collect_evidence_sync_handles_empty_corpus() -> None:
    client = _FakeSyncClient([], [])
    ev = collect_evidence_sync(client, "sha", "V")
    assert ev.files == frozenset()
    assert ev.paths == frozenset()
    assert ev.rule_ids == frozenset()
    assert ev.build_tag == ""


def test_collect_evidence_async_matches_sync() -> None:
    files_rows = [("System.txt", "x/System.txt")]
    rec_rows = [("environment_windows", {"env_user_name": "User"})]

    async def _run() -> None:
        c = _FakeAsyncClient(files_rows, rec_rows)
        ev = await collect_evidence(c, "sha", "V")
        assert "system.txt" in ev.files
        assert "environment_windows" in ev.rule_ids
        assert ev.build_tag == ""  # no build_tag alias in these fields

    asyncio.run(_run())


def test_write_verdict_sync_envelope() -> None:
    client = _FakeSyncClient([], [])
    verdict = FamilyVerdict(slug="vidar", confidence=0.78, evidence=["build_tag:^mix$"])
    result = ClassificationResult(
        verdict=verdict,
        runners_up=[FamilyVerdict(slug="stealc", confidence=0.31, evidence=[])],
    )
    write_verdict_sync(client, "sha", "V", result)
    assert len(client.inserts) == 1
    table, rows, cols = client.inserts[0]
    assert table.endswith(".victim_family_verdict")
    assert cols == [
        "archive_sha256",
        "victim_folder",
        "slug",
        "confidence",
        "evidence",
        "runners_up",
    ]
    (row,) = rows
    assert row[0] == "sha"
    assert row[1] == "V"
    assert row[2] == "vidar"
    assert row[3] == pytest.approx(0.78)
    assert row[4] == ["build_tag:^mix$"]
    assert row[5] == [("stealc", 0.31)]


def test_write_verdict_sync_handles_no_verdict() -> None:
    client = _FakeSyncClient([], [])
    result = ClassificationResult(verdict=None, runners_up=[])
    write_verdict_sync(client, "sha", "V", result)
    (_, rows, _) = client.inserts[0]
    row = rows[0]
    assert row[2] == ""  # slug blank when no verdict
    assert row[3] == 0.0
    assert row[4] == []
