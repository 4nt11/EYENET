"""Value types: tier MAX ordering and redaction masking edges."""

from __future__ import annotations

import pytest

from eyenet.classifier.ruleset import RuleMatch, max_tier
from eyenet.contracts.enums import SensitivityTier

pytestmark = pytest.mark.unit

N = SensitivityTier.NORMAL
R = SensitivityTier.RESTRICTED
C = SensitivityTier.CLASSIFIED


def test_max_tier_empty_is_normal() -> None:
    assert max_tier([]) is N  # the floor


@pytest.mark.parametrize(
    ("tiers", "expected"),
    [
        ([N, R, C], C),
        ([R, N], R),
        ([N, N], N),
        ([C], C),
    ],
)
def test_max_tier_picks_highest_by_order_not_alpha(
    tiers: list[SensitivityTier], expected: SensitivityTier
) -> None:
    # Alphabetic value sort would rank "classified" lowest — the explicit order
    # must win. (max(["normal","classified"]) lexically is "normal".)
    assert max_tier(tiers) is expected


def _match(text: str) -> RuleMatch:
    return RuleMatch(rule_name="r", tier_floor=R, start=0, end=len(text), matched_text=text)


def test_redact_short_span_fully_masked() -> None:
    # A span of <=4 chars has no last-4 to retain; mask it entirely.
    red = _match("abcd").redacted()
    assert red.matched_text == "****"
    assert red.tier_floor is R and red.rule_name == "r"


def test_redact_long_span_caps_star_run() -> None:
    red = _match("X" * 500).redacted()
    # capped leading stars (12) + last 4 retained — not a 500-char asterisk wall
    assert red.matched_text == "*" * 12 + "XXXX"
