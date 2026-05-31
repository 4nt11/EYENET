"""The deterministic regex spine: text + compiled ruleset -> tier-floor verdict.

Pure and I/O-free — no nsjail, no DB, no network. Re-running it on the same bytes
with the same ``ruleset_version`` MUST yield the same verdict; that
reproducibility is what makes the assigned tier defensible in court.

This stage returns a FLOOR only. The aggregator (a later slice) takes the MAX of
this floor against the other deterministic stages and decides the final tier.
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, Any

import structlog

from ._types import RegexVerdict, RuleMatch, max_tier

if TYPE_CHECKING:
    from ._types import CompiledRuleset

__all__ = ["classify"]

_log = structlog.get_logger()


def classify(text: str, ruleset: CompiledRuleset) -> RegexVerdict:
    """Match every rule against ``text`` and return the MAX tier floor + matches.

    Text is NFC-normalized once before matching (so a composed and a decomposed
    "é" classify identically); all reported offsets are into that normalized
    form. With no match the floor is NORMAL — this stage never lowers a tier.
    """
    normalized = unicodedata.normalize("NFC", text)

    matches: list[RuleMatch] = []
    for rule in ruleset.rules:
        pattern: Any = rule.pattern
        for m in pattern.finditer(normalized):
            matches.append(
                RuleMatch(
                    rule_name=rule.name,
                    tier_floor=rule.tier_floor,
                    start=m.start(),
                    end=m.end(),
                    matched_text=m.group(0),
                    lang=rule.lang,
                )
            )

    matches.sort(key=lambda rm: (rm.start, rm.rule_name))
    floor = max_tier(rm.tier_floor for rm in matches)

    # Provenance for the operational log — rule names + offsets only, NEVER the
    # raw matched span (logs are not clearance-gated).
    _log.info(
        "classify.regex",
        ruleset_version=ruleset.version,
        engine="re2",
        tier_floor=floor.value,
        n_matches=len(matches),
        rules=sorted({rm.rule_name for rm in matches}),
    )
    return RegexVerdict(
        tier_floor=floor,
        matches=tuple(matches),
        ruleset_version=ruleset.version,
    )
