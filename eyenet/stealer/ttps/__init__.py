# SPDX-License-Identifier: AGPL-3.0-or-later
"""MITRE ATT&CK catalog loader + rule-TTP resolver.

Loaded once at import time; the catalog is a hand-curated subset of
the ATT&CK framework (see mitre_catalog.yaml for scope + regen notes).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

_CATALOG_PATH = Path(__file__).resolve().parent / "mitre_catalog.yaml"
_RULES_DIR = Path(__file__).resolve().parents[1] / "rules" / "catalog"


@cache
def mitre_catalog() -> dict[str, dict[str, str]]:
    """Return the MITRE technique catalog as {id: {name, tactic, tactic_id, url}}."""
    data = yaml.safe_load(_CATALOG_PATH.read_text(encoding="utf-8"))
    return dict(data["techniques"])


@cache
def rule_to_ttps() -> dict[str, list[str]]:
    """Return {rule_id: [technique_id, ...]} by walking the rule catalog.

    Rules with an empty or missing ttps field are present as empty lists
    so the resolver can distinguish "no techniques for this rule" from
    "rule unknown". Container rules intentionally have [].
    """
    out: dict[str, list[str]] = {}
    for p in sorted(_RULES_DIR.glob("*.yaml")):
        spec = yaml.safe_load(p.read_text(encoding="utf-8"))
        out[spec["id"]] = list(spec.get("ttps") or [])
    return out


def resolve_techniques(
    rule_ids: list[str],
) -> list[dict[str, object]]:
    """For a list of fired rule_ids, return deduped technique rows ready
    for the API schema. Each row carries the catalog metadata + the list
    of rule_ids that contributed it (so the UI can hover to see 'fired
    by: passwords_block_title, cookies_netscape_tsv')."""
    catalog = mitre_catalog()
    rule_map = rule_to_ttps()
    # technique_id -> set of rule_ids that fired it
    by_technique: dict[str, set[str]] = {}
    for rid in rule_ids:
        for tid in rule_map.get(rid, []):
            by_technique.setdefault(tid, set()).add(rid)
    out: list[dict[str, object]] = []
    for tid, rules_set in by_technique.items():
        meta = catalog.get(tid)
        if meta is None:
            continue
        out.append(
            {
                "technique_id": tid,
                "name": meta["name"],
                "tactic": meta["tactic"],
                "tactic_id": meta["tactic_id"],
                "url": meta["url"],
                "fired_from_rules": sorted(rules_set),
            }
        )
    out.sort(key=lambda r: (r["tactic_id"], r["technique_id"]))
    return out


__all__ = ["mitre_catalog", "resolve_techniques", "rule_to_ttps"]
