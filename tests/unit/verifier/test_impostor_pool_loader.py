"""Unit tests for `_load_impostor_pool` — operator-grade input handling.

The loader must:
- silently return [] when no path is configured (path is None)
- warn loudly when the operator typo'd a path (path set but missing)
- skip + warn (never crash) on malformed JSONL lines
- skip + warn on records that don't match the {"bodies": [str, ...]} shape
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import structlog

from eyenet.verifier.service import _load_impostor_pool


def _events(captured: list[Any]) -> list[str]:
    return [rec["event"] for rec in captured]


@pytest.mark.unit
def test_none_path_silent_returns_empty() -> None:
    with structlog.testing.capture_logs() as caplog:
        out = _load_impostor_pool(None)
    assert out == []
    assert caplog == []


@pytest.mark.unit
def test_missing_path_logs_warning_and_returns_empty(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.jsonl"
    with structlog.testing.capture_logs() as caplog:
        out = _load_impostor_pool(missing)
    assert out == []
    assert "verifier.impostor_pool_missing" in _events(caplog)


@pytest.mark.unit
def test_malformed_json_line_skipped_and_logged(tmp_path: Path) -> None:
    pool = tmp_path / "pool.jsonl"
    pool.write_text(
        '{"bodies": ["one", "two"]}\nthis is not json at all\n{"bodies": ["three"]}\n',
        encoding="utf-8",
    )
    with structlog.testing.capture_logs() as caplog:
        out = _load_impostor_pool(pool)
    assert out == [["one", "two"], ["three"]]
    malformed = [r for r in caplog if r["event"] == "verifier.impostor_pool_malformed_line"]
    assert len(malformed) == 1
    assert malformed[0]["line_no"] == 2


@pytest.mark.unit
def test_invalid_record_shape_skipped_and_logged(tmp_path: Path) -> None:
    pool = tmp_path / "pool.jsonl"
    pool.write_text(
        json.dumps({"bodies": ["ok"]})
        + "\n"
        + json.dumps({"not_bodies": ["x"]})
        + "\n"  # missing "bodies"
        + json.dumps({"bodies": [1, 2, 3]})
        + "\n"  # not str list
        + json.dumps(["just", "a", "list"])
        + "\n",  # not a dict
        encoding="utf-8",
    )
    with structlog.testing.capture_logs() as caplog:
        out = _load_impostor_pool(pool)
    assert out == [["ok"]]
    invalid = [r for r in caplog if r["event"] == "verifier.impostor_pool_invalid_record"]
    assert len(invalid) == 3
    assert [r["line_no"] for r in invalid] == [2, 3, 4]


@pytest.mark.unit
def test_happy_path_returns_all_valid_records(tmp_path: Path) -> None:
    pool = tmp_path / "pool.jsonl"
    pool.write_text(
        json.dumps({"bodies": ["a1", "a2"]})
        + "\n"
        + "\n"  # blank line OK
        + json.dumps({"bodies": ["b1"]})
        + "\n",
        encoding="utf-8",
    )
    with structlog.testing.capture_logs() as caplog:
        out = _load_impostor_pool(pool)
    assert out == [["a1", "a2"], ["b1"]]
    assert caplog == []
