# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operational-infrastructure indicator extraction (anti-spam linkage §B).

Text in, typed indicator matches out. The patterns are DATA (the ``indicator_rule``
table), not hard-coded: :func:`compile_rules` turns rule rows into compiled
matchers, :func:`extract` runs them. The pure functions take a compiled ruleset so
they stay trivially testable and reusable by both the batch linker and the live
per-message sensor.

``extract_indicators(text)`` keeps the legacy ``set["<kind>:<value_norm>"]`` shape
the infra linker consumes; with no ruleset passed it uses the vendored default
catalog, so callers that don't touch the DB still work. Pass a DB-loaded compiled
ruleset (:func:`load_ruleset`) to honor operator enable/disable + custom rules.

``kind`` is an :class:`~eyenet.contracts.enums.InfrastructureKind` value, so matches
land in the shared ``infrastructure_artifact`` store.

Value convention: a pattern with ONE capturing group yields ``group(1)`` (the
``@handle`` without the ``@``); a pattern with none yields the whole match. Only
the handle rule uses a capturing group.

See ``development/linker-antispam-spec.md`` §3 and ``development/INDICATORS_PLAN.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import re2
import structlog

from eyenet.linker.indicator_rules import VENDORED_INDICATOR_RULES

_log = structlog.get_logger()

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from eyenet.contracts.indicator import IndicatorRuleRow
    from eyenet.storage.repository import BaseRepository

# RE2 is linear-time with no backtracking, so a pathological pattern cannot cause
# catastrophic matching (ReDoS) — that is why the ruleset can safely accept
# operator-custom regexes at all. MAX_TEXT_LEN is just a per-message cost bound,
# not a safety guard. RE2 also rejects lookbehind/backreferences at compile time,
# so an operator pattern using them is skipped here and rejected with a clear
# error at the API write boundary (Phase 4).
MAX_TEXT_LEN = 200_000

# Handles that are structural noise, not crew infrastructure (@everyone-style
# mentions, generic service handles). Dropped for the handle kind so they never
# pollute the artifact store; the linker's max_df guard is the general backstop.
_HANDLE_KIND = "handle_other_platform"
_HANDLE_STOPLIST = frozenset({"admin", "everyone", "channel", "all", "here"})


@dataclass(frozen=True)
class CompiledRule:
    kind: str
    regex: Any  # re2 compiled pattern (google-re2 ships no stubs)
    fold_case: bool


@dataclass(frozen=True)
class ExtractedIndicator:
    kind: str
    value_raw: str  # surface form (evidence)
    value_norm: str  # dedup key
    char_offset: int  # start of the match in the text


def _compile_one(kind: str, pattern: str, fold_case: bool) -> CompiledRule | None:
    """Compile one rule with RE2, or return ``None`` if invalid (bad syntax, or a
    lookbehind/backreference RE2 does not support).

    Returning ``None`` (never raising) keeps one bad operator rule from disabling
    the whole extractor; the async loader logs every skip (never a silent drop).
    """
    try:
        rx = re2.compile(pattern)
    except re2.error:
        return None
    return CompiledRule(kind=kind, regex=rx, fold_case=fold_case)


def compile_rules(
    rules: Iterable[IndicatorRuleRow],
) -> tuple[list[CompiledRule], list[tuple[str, str]]]:
    """Compile rule rows. Return ``(compiled, skipped)`` where skipped is
    ``[(pattern, reason)]`` for the caller to log."""
    compiled: list[CompiledRule] = []
    skipped: list[tuple[str, str]] = []
    for r in rules:
        c = _compile_one(r.kind, r.pattern, r.fold_case)
        if c is None:
            skipped.append((r.pattern, "invalid regex (RE2: bad syntax / lookbehind / backref)"))
        else:
            compiled.append(c)
    return compiled, skipped


def _compile_vendored() -> list[CompiledRule]:
    """Compile the vendored default catalog (no DB). A bad vendored pattern is a
    bug the engine tests catch, so skips here are dropped silently by design."""
    out: list[CompiledRule] = []
    for r in VENDORED_INDICATOR_RULES:
        c = _compile_one(r["kind"], r["pattern"], r["fold_case"])
        if c is not None:
            out.append(c)
    return out


_DEFAULT_COMPILED: list[CompiledRule] = _compile_vendored()


def default_ruleset() -> list[CompiledRule]:
    """The vendored default catalog, compiled. Fallback when no DB ruleset loaded."""
    return list(_DEFAULT_COMPILED)


def extract(text: str | None, compiled: Sequence[CompiledRule]) -> list[ExtractedIndicator]:
    """Return the distinct indicators in ``text`` (deduped by ``(kind, value_norm)``,
    first occurrence wins). Empty for empty text."""
    if not text:
        return []
    if len(text) > MAX_TEXT_LEN:
        text = text[:MAX_TEXT_LEN]  # cost guard; head is where ad infra lives
    seen: dict[tuple[str, str], ExtractedIndicator] = {}
    for rule in compiled:
        has_group = rule.regex.groups >= 1
        for m in rule.regex.finditer(text):
            raw = m.group(1) if has_group else m.group(0)
            if not raw:
                continue
            norm = raw.lower() if rule.fold_case else raw
            if rule.kind == _HANDLE_KIND and norm in _HANDLE_STOPLIST:
                continue
            # Offset points at the stored value: the captured group when there is
            # one (the handle after '@'), else the whole match.
            offset = m.start(1) if has_group else m.start()
            key = (rule.kind, norm)
            if key not in seen:
                seen[key] = ExtractedIndicator(
                    kind=rule.kind, value_raw=raw, value_norm=norm, char_offset=offset
                )
    return list(seen.values())


def extract_indicators(
    text: str | None, compiled: Sequence[CompiledRule] | None = None
) -> set[str]:
    """Legacy token set ``{"<kind>:<value_norm>"}`` for the infra linker.

    With no ``compiled`` ruleset, uses the vendored default catalog.
    """
    rules = compiled if compiled is not None else _DEFAULT_COMPILED
    return {f"{i.kind}:{i.value_norm}" for i in extract(text, rules)}


async def load_ruleset(storage: BaseRepository) -> list[CompiledRule]:
    """Load ENABLED rules from the DB, compile them, and log any that fail to
    compile (so a bad operator rule degrades one kind, not the whole extractor)."""
    rows = await storage.list_indicator_rules(enabled_only=True)
    compiled, skipped = compile_rules(rows)
    for pattern, reason in skipped:
        _log.warning("indicator_rule_skipped", reason=reason, pattern=pattern)
    return compiled


__all__ = [
    "CompiledRule",
    "ExtractedIndicator",
    "compile_rules",
    "default_ruleset",
    "extract",
    "extract_indicators",
    "load_ruleset",
]
