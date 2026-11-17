"""Vendored stealer family catalog.

A family is the operator-facing identity of a malware strain or combolist
class. Rules carry a ``family`` tag that references one of these slugs,
giving us a system-defined enum that stays current faster than our
parser rules do: a new family can be catalogued the day it appears,
even before anyone writes a parsing rule for it.

Load with::

    from eyenet.stealer.families import load_families, valid_slugs
    families = load_families()
    slugs = valid_slugs()  # set[str]

Unknown family slugs on a rule are logged via :func:`validate_rule_family`
as WARNINGs, not hard errors, so an experimental or in-flight rule
doesn't block the whole catalog load.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TypedDict

import yaml

_FAMILIES_DIR = Path(__file__).resolve().parent
_log = logging.getLogger(__name__)


class FamilyRef(TypedDict, total=False):
    title: str
    url: str


class Family(TypedDict, total=False):
    slug: str
    name: str
    status: str
    first_seen_year: int
    aliases: list[str]
    signature_files: list[str]
    loaders: list[str]
    distribution_channels: list[str]
    references: list[FamilyRef]
    notes: str


_VALID_STATUSES = frozenset({"active", "retired", "dormant", "new", "suspected"})


def load_families() -> list[Family]:
    """Return every family.yaml in the catalog directory.

    Slugs must be unique. Each entry is lightly validated: slug + name +
    status required; status must be one of the enum values. Unknown
    fields are preserved for forward-compat.
    """
    out: list[Family] = []
    seen: set[str] = set()
    for p in sorted(_FAMILIES_DIR.glob("*.yaml")):
        fam = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(fam, dict):
            raise ValueError(f"{p.name}: not a family (not a mapping)")
        for req in ("slug", "name", "status"):
            if req not in fam:
                raise ValueError(f"{p.name}: missing required field '{req}'")
        if fam["status"] not in _VALID_STATUSES:
            raise ValueError(
                f"{p.name}: status {fam['status']!r} not in {sorted(_VALID_STATUSES)}"
            )
        if fam["slug"] in seen:
            raise ValueError(f"{p.name}: duplicate slug {fam['slug']!r}")
        seen.add(fam["slug"])
        out.append(fam)
    return out


def valid_slugs() -> set[str]:
    """Set of family slugs currently in the catalog."""
    return {f["slug"] for f in load_families()}


def validate_rule_family(rule_id: str, rule_family: str, slugs: set[str] | None = None) -> None:
    """Log a WARN when a rule references a family slug not in the catalog.

    Called at rule-catalog load time. We deliberately do NOT raise:
    experimental rules referencing a yet-unlisted family should still
    load, so the operator can author the two in either order.
    """
    known = slugs if slugs is not None else valid_slugs()
    if rule_family not in known:
        _log.warning(
            "rule %r references unknown family %r (add it in eyenet/stealer/families/)",
            rule_id, rule_family,
        )
