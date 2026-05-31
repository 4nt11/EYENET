"""apply_llm_advisory(): flag-only LLM merge — tier is NEVER lowered (§4).

Pure; synthetic verdict + advisory. Covers the tripwire flag (higher only,
short-circuited at CLASSIFIED), the universal analysis attach, the
LLM_UNAVAILABLE informational flag, the redaction of LLM free-text, and the
audit payload's no-raw-leak invariant.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from eyenet.classifier.aggregate import (
    ReviewKind,
    aggregate,
    apply_llm_advisory,
    classification_audit_payload,
)
from eyenet.classifier.llm import LlmAdvisory, LlmUnavailable
from eyenet.classifier.presidio._types import PresidioVerdict
from eyenet.classifier.ruleset._types import RegexVerdict, RuleMatch
from eyenet.classifier.sandbox import ExtractResult
from eyenet.contracts.enums import SensitivityTier

pytestmark = pytest.mark.unit

N = SensitivityTier.NORMAL
R = SensitivityTier.RESTRICTED
C = SensitivityTier.CLASSIFIED


def _extract() -> ExtractResult:
    return ExtractResult(
        text="hello", meta={"doc_kind": "pdf", "empty": False, "ocr_applied": False}
    )


def _regex(floor: SensitivityTier = N, matches: Sequence[RuleMatch] = ()) -> RegexVerdict:
    return RegexVerdict(tier_floor=floor, matches=tuple(matches), ruleset_version="v3")


def _presidio(floor: SensitivityTier = N) -> PresidioVerdict:
    return PresidioVerdict(tier_floor=floor, matches=(), map_version="v1")


def _verdict(regex_floor: SensitivityTier = N, presidio_floor: SensitivityTier = N):
    return aggregate(_extract(), _regex(regex_floor), _presidio(presidio_floor))


def _adv(
    tier: SensitivityTier,
    *,
    summary: str = "an analysis",
    indicators: Sequence[str] = ("x",),
    confidence: str = "low",
) -> LlmAdvisory:
    return LlmAdvisory(
        suggested_tier=tier,
        summary=summary,
        indicators=tuple(indicators),
        confidence=confidence,  # type: ignore[arg-type]
        model="test-model",
        attempts=1,
    )


def test_higher_suggestion_raises_flag_but_tier_unchanged() -> None:
    base = _verdict(N, N)
    out = apply_llm_advisory(base, _adv(C))
    assert out.tier is N  # BINDING tier never moves
    assert out.llm is not None
    kinds = [f.kind for f in out.review_flags]
    assert ReviewKind.LLM_HIGHER_TIER in kinds
    flag = next(f for f in out.review_flags if f.kind is ReviewKind.LLM_HIGHER_TIER)
    assert flag.suggested_tier is C


def test_same_or_lower_suggestion_attaches_analysis_no_flag() -> None:
    base = _verdict(R, N)  # deterministic tier RESTRICTED
    out = apply_llm_advisory(base, _adv(N))  # LLM judged it lower
    assert out.tier is R  # never lowered
    assert out.llm is not None
    assert all(f.kind is not ReviewKind.LLM_HIGHER_TIER for f in out.review_flags)


def test_classified_short_circuits_tripwire_but_still_attaches() -> None:
    base = _verdict(C, N)  # already at the top
    out = apply_llm_advisory(base, _adv(C))
    assert out.tier is C
    assert out.llm is not None
    assert all(f.kind is not ReviewKind.LLM_HIGHER_TIER for f in out.review_flags)


def test_unavailable_raises_informational_flag_only() -> None:
    base = _verdict(N, N)
    out = apply_llm_advisory(base, LlmUnavailable(reason="timeout", detail="", attempts=3))
    assert out.tier is N
    assert out.llm is None  # nothing to attach
    kinds = [f.kind for f in out.review_flags]
    assert ReviewKind.LLM_UNAVAILABLE in kinds


def test_existing_flags_are_preserved() -> None:
    base = _verdict(N, N)
    out = apply_llm_advisory(base, _adv(R))
    # the higher-tier flag is appended, not replacing
    assert len(out.review_flags) >= 1


def test_redacted_drops_llm_freetext() -> None:
    base = _verdict(N, N)
    out = apply_llm_advisory(base, _adv(R, summary="SECRET informant name", indicators=("leak",)))
    red = out.redacted()
    assert red.llm is not None
    assert red.llm.summary == "[redacted]"
    assert red.llm.indicators == ()
    # original untouched
    assert out.llm is not None
    assert out.llm.summary == "SECRET informant name"


def test_audit_payload_carries_safe_llm_fields_only() -> None:
    base = _verdict(N, N)
    out = apply_llm_advisory(
        base, _adv(R, summary="SECRET informant name", indicators=("leak",), confidence="medium")
    )
    payload = classification_audit_payload(out)
    assert "llm" in payload
    llm = payload["llm"]
    assert isinstance(llm, dict)
    assert llm["suggested_tier"] == "restricted"
    assert llm["confidence"] == "medium"
    assert llm["model"] == "test-model"
    # No raw analysis text leaks into the (non-clearance-gated) audit log.
    assert "summary" not in llm
    assert "indicators" not in llm
    assert "SECRET informant name" not in json.dumps(payload)


def test_payload_is_json_serializable() -> None:
    base = _verdict(N, N)
    out = apply_llm_advisory(base, _adv(R))
    json.dumps(classification_audit_payload(out))  # must not raise


# ── LLM x over-classification flag coupling (slice 9) ────────────────────────-


def _over_class_verdict():
    """A verdict carrying a POSSIBLE_OVER_CLASSIFICATION flag (FP-prone + counter)."""
    regex = _regex(
        R,
        [
            RuleMatch(
                rule_name="corp_confidential_en",
                tier_floor=R,
                start=0,
                end=17,
                matched_text="INTERNAL USE ONLY",
            ),
            RuleMatch(
                rule_name="fp_template_placeholder",
                tier_floor=N,
                start=40,
                end=51,
                matched_text="lorem ipsum",
            ),
        ],
    )
    return aggregate(_extract(), regex, _presidio(N))


def test_llm_normal_corroborates_over_classification_flag() -> None:
    base = _over_class_verdict()
    assert any(f.kind is ReviewKind.POSSIBLE_OVER_CLASSIFICATION for f in base.review_flags)
    out = apply_llm_advisory(base, _adv(N))  # LLM agrees: not sensitive
    assert out.tier is R  # tier NEVER moves (§0)
    flag = next(f for f in out.review_flags if f.kind is ReviewKind.POSSIBLE_OVER_CLASSIFICATION)
    assert flag.corroborated is True


def test_llm_sensitive_suppresses_over_classification_flag() -> None:
    base = _over_class_verdict()
    out = apply_llm_advisory(base, _adv(C))  # LLM disagrees: it IS sensitive
    assert out.tier is R  # tier NEVER moves
    assert all(f.kind is not ReviewKind.POSSIBLE_OVER_CLASSIFICATION for f in out.review_flags)
    # the LLM's own higher-tier tripwire still fires (suggested C > tier R)
    assert any(f.kind is ReviewKind.LLM_HIGHER_TIER for f in out.review_flags)


def test_llm_unavailable_leaves_over_classification_flag_independent() -> None:
    base = _over_class_verdict()
    out = apply_llm_advisory(base, LlmUnavailable(reason="timeout", detail="", attempts=1))
    flag = next(f for f in out.review_flags if f.kind is ReviewKind.POSSIBLE_OVER_CLASSIFICATION)
    assert flag.corroborated is False  # no LLM opinion → untouched
