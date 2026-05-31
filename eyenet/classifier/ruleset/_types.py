"""Value types for the regex ruleset engine — dependency-free, frozen.

These carry the *provenance* that makes a classification defensible: which rule
fired, where (offset into the extracted text), and what it matched. The tier
arithmetic is a monotone MAX over an explicit order — never StrEnum value
ordering, which is alphabetic and would silently mis-rank.

``matched_text`` holds the RAW captured span. This is operator-grade evidence
(full content retained, access journaled, clearance-gated) — offsets alone are
not court-verifiable ("rule X matched at offset N" is unfalsifiable without the
bytes). Use :func:`redact` / :meth:`RuleMatch.redacted` before anything reaches
a log line or a lower-clearance surface; structured logs are NOT clearance-gated.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from eyenet.contracts.enums import SensitivityTier

if TYPE_CHECKING:
    from collections.abc import Iterable

# Redaction shape: keep the last N chars, cap the leading star run so a 4 KB
# private-key block doesn't become a 4 KB asterisk wall in a log line.
_REDACT_TAIL = 4
_REDACT_STAR_CAP = 12

# Explicit monotone order. SensitivityTier is a StrEnum; comparing its *values*
# would sort alphabetically ("classified" < "normal" < "restricted"), which is
# nonsense for a tier floor. Rank here, nowhere else.
_TIER_ORDER: dict[SensitivityTier, int] = {
    SensitivityTier.NORMAL: 0,
    SensitivityTier.RESTRICTED: 1,
    SensitivityTier.CLASSIFIED: 2,
}


def max_tier(tiers: Iterable[SensitivityTier]) -> SensitivityTier:
    """Return the highest tier, or NORMAL for an empty iterable (the floor)."""
    highest = SensitivityTier.NORMAL
    for tier in tiers:
        if _TIER_ORDER[tier] > _TIER_ORDER[highest]:
            highest = tier
    return highest


def _mask(span: str) -> str:
    """Mask a captured span for logs: keep last 4 chars, cap the star run.

    Length-preserving up to a 12-char cap so a 4 KB private-key block doesn't
    become a 4 KB asterisk wall in a log line. ``123-45-6789`` -> ``*******6789``.
    """
    n = len(span)
    if n <= _REDACT_TAIL:
        return "*" * n
    return "*" * min(n - _REDACT_TAIL, _REDACT_STAR_CAP) + span[-_REDACT_TAIL:]


@dataclass(frozen=True, slots=True)
class RuleMatch:
    """One rule firing at one location in the extracted text."""

    rule_name: str
    tier_floor: SensitivityTier
    start: int
    end: int
    matched_text: str
    lang: str | None = None

    def redacted(self) -> RuleMatch:
        """Return a copy with ``matched_text`` masked — safe for logs/UI."""
        return replace(self, matched_text=_mask(self.matched_text))


@dataclass(frozen=True, slots=True)
class RegexVerdict:
    """The regex stage's verdict for one document: a tier floor + provenance.

    ``tier_floor`` is the MAX over all matched rules' floors, or NORMAL when no
    rule fired. This is a FLOOR only — the aggregator (a later slice) takes the
    MAX of this against the other deterministic stages.
    """

    tier_floor: SensitivityTier
    matches: tuple[RuleMatch, ...]
    ruleset_version: str
    engine: str = "re2"

    def redacted(self) -> RegexVerdict:
        """Return a copy with every match's ``matched_text`` masked."""
        return replace(self, matches=tuple(m.redacted() for m in self.matches))


@dataclass(frozen=True, slots=True)
class CompiledRule:
    """A loaded, eagerly-compiled rule. ``pattern`` is a ``re2`` pattern object.

    Typed ``object`` because google-re2 ships no usable stubs; the engine narrows
    it at the one call site. Keeping the ``re2`` import out of this leaf module
    preserves its dependency-free posture (mirrors the sandbox ``_types``).
    """

    name: str
    pattern: object
    tier_floor: SensitivityTier
    lang: str | None


@dataclass(frozen=True, slots=True)
class CompiledRuleset:
    """An immutable, fully-compiled ruleset ready for :func:`classify`."""

    version: str
    rules: tuple[CompiledRule, ...]
