"""Operator incident-rule compilation, validation, and matching.

A rule is an RE2 pattern -> taxonomy label, layered ON TOP of the built-in field-grounded
prefilter signals (eyenet/incidents/prefilter.py) — it never modifies them. The classifier
service compiles enabled rules and fires them alongside the built-ins, so operators tune
detection live without a redeploy.

Rules match on the SAME normalized text the built-in prefilter uses (NFC + confusable
fold), so homoglyph evasion is handled identically.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

import re2

from eyenet.incidents.prefilter import _CONFUSABLES, _RE2_OPTIONS, SIGNALS
from eyenet.telemetry import get_logger

_log = get_logger()

TAXONOMY_LABELS: frozenset[str] = frozenset(
    {"incident", "leak", "infostealer", "access_sale", "actor_ops", "tooling"}
)
BUILTIN_SIGNAL_NAMES: frozenset[str] = frozenset(s.name for s in SIGNALS)


@dataclass(frozen=True)
class CompiledRule:
    name: str
    pattern: Any  # compiled re2 pattern
    label: str


def validate_pattern(pattern: str) -> str | None:
    """Return None if ``pattern`` compiles as RE2, else the error message."""
    try:
        re2.compile(pattern, _RE2_OPTIONS)
    except Exception as exc:  # re2 raises on invalid syntax / unsupported constructs
        return str(exc)
    return None


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text).translate(_CONFUSABLES)


def compile_rules(rows: list[Any]) -> list[CompiledRule]:
    """Compile enabled rule rows (objects with .name/.pattern/.label/.enabled). A row with
    a bad pattern is skipped defensively (it should have been rejected at create time)."""
    out: list[CompiledRule] = []
    for r in rows:
        if not getattr(r, "enabled", True):
            continue
        try:
            pat = re2.compile(r.pattern, _RE2_OPTIONS)
        except Exception as exc:  # nosec B112 — logged skip; one corrupt rule must not crash the service
            _log.warning(
                "incident.rule_compile_failed",
                name=getattr(r, "name", "?"),
                error=str(exc),
            )
            continue
        out.append(CompiledRule(name=r.name, pattern=pat, label=r.label))
    return out


def match_labels(text: str, compiled: list[CompiledRule]) -> set[str]:
    """Taxonomy labels whose operator rule matches ``text`` (normalized like the prefilter)."""
    if not compiled:
        return set()
    norm = _normalize(text)
    return {c.label for c in compiled if c.pattern.search(norm) is not None}


__all__ = [
    "BUILTIN_SIGNAL_NAMES",
    "TAXONOMY_LABELS",
    "CompiledRule",
    "compile_rules",
    "match_labels",
    "validate_pattern",
]
