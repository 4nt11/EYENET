"""Smoke: every vendored rule in the catalog loads, has a valid shape, and
runs through the engine without raising on an empty victim folder."""

from __future__ import annotations

import pytest

from eyenet.stealer.rules.catalog import load_catalog
from eyenet.stealer.rules.engine import run_rules
from eyenet.stealer.rules.types import VictimFolder

pytestmark = pytest.mark.unit


def test_catalog_loads_with_unique_ids() -> None:
    rules = load_catalog()
    assert len(rules) >= 10, f"expected at least 10 base rules, got {len(rules)}"
    ids = [r["id"] for r in rules]
    assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"


def test_catalog_runs_on_empty_folder() -> None:
    rules = load_catalog()
    result = run_rules(rules, VictimFolder(root_name="empty", files=()))
    # The combolist fallback container (priority 1, min_score 0) matches
    # unconditionally; every family-specific container misses.
    assert result.family == "combolist"
    assert result.fields == {}
    specific = [e for e in result.evaluations if e.layer == "container" and e.family != "combolist"]
    assert all(not e.matched for e in specific)


def test_catalog_families_set() -> None:
    rules = load_catalog()
    families = {r["family"] for r in rules}
    assert families >= {"lumma", "redline", "stealc", "json_v2"}


def test_catalog_every_rule_declares_match_type() -> None:
    rules = load_catalog()
    for r in rules:
        assert r.get("match", {}).get("type"), f"{r['id']}: missing match.type"
        assert r.get("layer") in ("container", "content"), f"{r['id']}: bad layer"
        assert r.get("priority") is not None, f"{r['id']}: missing priority"
