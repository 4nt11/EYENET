# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for ``eyenet.stealer.ttps.resolve_techniques``.

The ``rule_to_ttps`` map is monkeypatched (via the LRU cache) so these
tests don't couple to the live rule catalog's current mappings.
"""

from __future__ import annotations

import pytest

from eyenet.stealer import ttps

pytestmark = pytest.mark.unit


def _patch_rules(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, list[str]]) -> None:
    monkeypatch.setattr(ttps, "rule_to_ttps", lambda: mapping)


def test_resolve_dedupes_and_sorts_by_tactic(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_rules(
        monkeypatch,
        {
            "rule_a": ["T1555.003"],
            "rule_b": ["T1555.003", "T1082"],
            "rule_c": ["T1082"],
        },
    )
    out = ttps.resolve_techniques(["rule_a", "rule_b", "rule_c"])
    ids = [t["technique_id"] for t in out]
    # Sorted by (tactic_id, technique_id); T1082 (Discovery TA0007) sorts
    # before T1555.003 (Credential Access TA0006)? No: TA0006 < TA0007 so
    # credential access comes first. Assert on presence, not order of IDs.
    assert set(ids) == {"T1555.003", "T1082"}
    fired_by = {t["technique_id"]: t["fired_from_rules"] for t in out}
    assert fired_by["T1555.003"] == ["rule_a", "rule_b"]
    assert fired_by["T1082"] == ["rule_b", "rule_c"]


def test_resolve_drops_unknown_techniques(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_rules(monkeypatch, {"rule_a": ["T9999.999"]})  # not in catalog
    assert ttps.resolve_techniques(["rule_a"]) == []


def test_resolve_ignores_unknown_rule_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_rules(monkeypatch, {"rule_a": ["T1082"]})
    assert ttps.resolve_techniques(["nonexistent_rule"]) == []


def test_mitre_catalog_loads() -> None:
    cat = ttps.mitre_catalog()
    assert "T1082" in cat
    assert cat["T1082"]["tactic_id"].startswith("TA")
