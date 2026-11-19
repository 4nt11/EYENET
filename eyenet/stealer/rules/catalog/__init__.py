"""Vendored base rule catalog.

Load with::

    from eyenet.stealer.rules.catalog import load_catalog
    rules = load_catalog()

The directory layout is one rule per YAML file. Rule ids must be unique
across the catalog; the loader asserts that at import time.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml

from eyenet.stealer.families import valid_slugs, validate_rule_family

if TYPE_CHECKING:
    from eyenet.stealer.rules.types import RuleSpec

_CATALOG_DIR = Path(__file__).resolve().parent


def load_catalog() -> list[RuleSpec]:
    """Return every rule.yaml in the catalog directory as a list of dicts.

    Rule ids are asserted unique. The caller is responsible for JSON-Schema
    validation (once the schema lands); this loader does the minimal
    parse + uniqueness check needed to bootstrap the pipeline.
    """
    rules: list[RuleSpec] = []
    seen: set[str] = set()
    known_families = valid_slugs()
    for p in sorted(_CATALOG_DIR.glob("*.yaml")):
        rule = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(rule, dict) or "id" not in rule:
            raise ValueError(f"{p.name}: not a rule (missing id)")
        rid = rule["id"]
        if rid in seen:
            raise ValueError(f"{p.name}: duplicate rule id {rid!r}")
        seen.add(rid)
        fam = rule.get("family")
        if fam:
            validate_rule_family(rid, fam, slugs=known_families)
        rules.append(cast("RuleSpec", rule))
    return rules
