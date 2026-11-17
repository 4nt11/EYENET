# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every rule's ``ttps:`` entries must resolve in the MITRE catalog.

Catches typos ('T1555.0003' vs 'T1555.003'), orphan techniques (rule
references a technique the catalog doesn't define), and catalog-side
drift (catalog claims a technique but no rule uses it is fine - the
inverse would mean a rule writer added a technique without updating
the catalog).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_CATALOG_DIR = Path(__file__).resolve().parents[3] / "eyenet" / "stealer" / "rules" / "catalog"
_MITRE_PATH = Path(__file__).resolve().parents[3] / "eyenet" / "stealer" / "ttps" / "mitre_catalog.yaml"


def test_every_rule_ttp_resolves_in_mitre_catalog() -> None:
    mitre = yaml.safe_load(_MITRE_PATH.read_text(encoding="utf-8"))
    known_techniques: set[str] = set(mitre["techniques"].keys())

    missing: dict[str, list[str]] = {}
    for rule_path in sorted(_CATALOG_DIR.glob("*.yaml")):
        rule = yaml.safe_load(rule_path.read_text(encoding="utf-8"))
        ttps = rule.get("ttps") or []
        for t in ttps:
            if t not in known_techniques:
                missing.setdefault(rule_path.name, []).append(t)

    assert missing == {}, (
        "rules reference techniques not in eyenet/stealer/ttps/mitre_catalog.yaml: "
        f"{missing}"
    )


def test_every_rule_has_ttps_field() -> None:
    """Every rule YAML must declare a ``ttps:`` field (possibly empty list).
    Container rules declare [] because they are family markers, not
    behavior claims.
    """
    missing_field: list[str] = []
    for rule_path in sorted(_CATALOG_DIR.glob("*.yaml")):
        rule = yaml.safe_load(rule_path.read_text(encoding="utf-8"))
        if "ttps" not in rule:
            missing_field.append(rule_path.name)
    assert missing_field == [], (
        "rule YAMLs missing ttps field (even [] is fine): " f"{missing_field}"
    )
