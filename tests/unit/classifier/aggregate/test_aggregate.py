"""aggregate(): monotone MAX of the three deterministic floors, fail-closed.

Pure decision logic — synthetic RegexVerdict / PresidioVerdict / ExtractResult
inputs, no nsjail, no venv, no models. Covers the §4 binding MAX, the §0
fail-closed paths, the LLM short-circuit gate, and the flag-only counter-signal
path (the tier is NEVER lowered).
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from eyenet.classifier.aggregate import ReviewKind, aggregate
from eyenet.classifier.presidio._types import PresidioMatch, PresidioVerdict
from eyenet.classifier.ruleset._types import RegexVerdict, RuleMatch
from eyenet.classifier.sandbox import ExtractResult, FailedClosed, FailReason
from eyenet.contracts.enums import SensitivityTier

pytestmark = pytest.mark.unit

N = SensitivityTier.NORMAL
R = SensitivityTier.RESTRICTED
C = SensitivityTier.CLASSIFIED


def _extract(text: str = "hello world", **meta: object) -> ExtractResult:
    base: dict[str, object] = {"doc_kind": "pdf", "empty": not text.strip(), "ocr_applied": False}
    base.update(meta)
    return ExtractResult(text=text, meta=base)


def _rule(name: str, floor: SensitivityTier, *, start: int = 0, text: str = "MARK") -> RuleMatch:
    return RuleMatch(
        rule_name=name, tier_floor=floor, start=start, end=start + len(text), matched_text=text
    )


def _regex(floor: SensitivityTier = N, matches: Sequence[RuleMatch] = ()) -> RegexVerdict:
    return RegexVerdict(tier_floor=floor, matches=tuple(matches), ruleset_version="v3")


def _pmatch(entity: str, floor: SensitivityTier, *, start: int = 0) -> PresidioMatch:
    return PresidioMatch(
        entity_type=entity,
        tier_floor=floor,
        start=start,
        end=start + 4,
        score=0.9,
        language="es",
        matched_text="Juan",
    )


def _presidio(
    floor: SensitivityTier = N,
    matches: Sequence[PresidioMatch] = (),
    *,
    fail_closed: bool = False,
) -> PresidioVerdict:
    return PresidioVerdict(
        tier_floor=floor, matches=tuple(matches), map_version="v1", fail_closed=fail_closed
    )


# ── binding MAX ──────────────────────────────────────────────────────────────


def test_all_normal_is_normal() -> None:
    v = aggregate(_extract(), _regex(N), _presidio(N))
    assert v.tier is N
    assert v.fail_closed is False
    assert v.review_flags == ()


@pytest.mark.parametrize(
    ("regex_floor", "presidio_floor", "expected"),
    [
        (R, N, R),  # regex alone drives it
        (N, R, R),  # presidio alone drives it
        (C, N, C),
        (N, C, C),
        (R, C, C),  # MAX of mixed floors
        (C, R, C),
    ],
)
def test_max_binding(
    regex_floor: SensitivityTier, presidio_floor: SensitivityTier, expected: SensitivityTier
) -> None:
    v = aggregate(_extract(), _regex(regex_floor), _presidio(presidio_floor))
    assert v.tier is expected


# ── §0 fail-closed ─────────────────────────────────────────────────────────--


def test_failed_extraction_forces_classified() -> None:
    fc = FailedClosed(reason=FailReason.PARSER_KILLED, detail="SIGSYS at parse")
    v = aggregate(fc, _regex(N), _presidio(N))
    assert v.tier is C
    assert v.fail_closed is True
    assert v.consult_llm is False
    ext = next(p for p in v.provenance if p.stage == "extraction")
    assert ext.fail_closed is True
    assert ext.version == FailReason.PARSER_KILLED.value
    assert ext.detail == "SIGSYS at parse"


def test_presidio_fail_closed_propagates() -> None:
    v = aggregate(_extract(), _regex(N), _presidio(C, fail_closed=True))
    assert v.tier is C
    assert v.fail_closed is True
    assert v.consult_llm is False


def test_empty_but_successful_extraction_is_normal_floor() -> None:
    # §0 'empty != normal' is the EXTRACTION layer's call; a successful empty
    # ExtractResult is trusted-empty, floor NORMAL — the aggregator does not
    # second-guess a clean extraction.
    v = aggregate(_extract(text="   "), _regex(N), _presidio(N))
    assert v.tier is N
    assert v.fail_closed is False
    ext = next(p for p in v.provenance if p.stage == "extraction")
    assert ext.tier_floor is N


# ── §4 LLM short-circuit gate ──────────────────────────────────────────────--


@pytest.mark.parametrize(
    ("regex_floor", "presidio_floor", "consult"),
    [(N, N, True), (R, N, True), (N, R, True), (C, N, False), (N, C, False)],
)
def test_consult_llm_gate(
    regex_floor: SensitivityTier, presidio_floor: SensitivityTier, consult: bool
) -> None:
    v = aggregate(_extract(), _regex(regex_floor), _presidio(presidio_floor))
    assert v.consult_llm is consult


def test_consult_llm_false_on_fail_closed_even_below_classified() -> None:
    # fail_closed forces CLASSIFIED, so the gate is closed regardless.
    fc = FailedClosed(reason=FailReason.TIMEOUT, detail="budget")
    v = aggregate(fc, _regex(N), _presidio(N))
    assert v.consult_llm is False


# ── counter-signal flag (flag-only; tier NEVER lowered) ─────────────────────--


def test_counter_signal_flags_fp_prone_tier() -> None:
    regex = _regex(
        R,
        [
            _rule("corp_confidential_en", R, start=0, text="INTERNAL USE ONLY"),
            _rule("fp_template_placeholder", N, start=40, text="lorem ipsum"),
        ],
    )
    v = aggregate(_extract(), regex, _presidio(N))
    assert v.tier is R  # tier UNCHANGED
    assert len(v.review_flags) == 1
    flag = v.review_flags[0]
    assert flag.kind is ReviewKind.POSSIBLE_OVER_CLASSIFICATION
    assert flag.suggested_tier is N


def test_no_flag_when_hard_rule_drives_tier() -> None:
    # An SSN (not FP-prone) at the tier blocks the flag even with a counter-signal.
    regex = _regex(
        R,
        [
            _rule("pii_us_ssn", R, start=0, text="123-45-6789"),
            _rule("fp_template_placeholder", N, start=40, text="john doe"),
        ],
    )
    v = aggregate(_extract(), regex, _presidio(N))
    assert v.tier is R
    assert v.review_flags == ()


def test_no_flag_when_presidio_drives_tier() -> None:
    # PII drove the tier — a counter-signal in the regex stage is not evidence
    # the PERSON cluster is a false positive.
    regex = _regex(N, [_rule("fp_creative_works", N, text="secret menu")])
    presidio = _presidio(R, [_pmatch("EMAIL_ADDRESS", R)])
    v = aggregate(_extract(), regex, presidio)
    assert v.tier is R
    assert v.review_flags == ()


def test_no_flag_when_mixed_fp_and_hard_at_tier() -> None:
    regex = _regex(
        R,
        [
            _rule("corp_confidential_en", R, start=0, text="INTERNAL USE ONLY"),
            _rule("pii_us_ssn", R, start=30, text="123-45-6789"),
            _rule("fp_template_placeholder", N, start=60, text="lorem ipsum"),
        ],
    )
    v = aggregate(_extract(), regex, _presidio(N))
    assert v.review_flags == ()


def test_no_flag_without_counter_signal() -> None:
    regex = _regex(R, [_rule("corp_confidential_en", R, text="INTERNAL USE ONLY")])
    v = aggregate(_extract(), regex, _presidio(N))
    assert v.review_flags == ()


def test_no_flag_at_normal_tier() -> None:
    regex = _regex(N, [_rule("fp_template_placeholder", N, text="lorem ipsum")])
    v = aggregate(_extract(), regex, _presidio(N))
    assert v.tier is N
    assert v.review_flags == ()


def test_no_flag_on_fail_closed() -> None:
    fc = FailedClosed(reason=FailReason.SANDBOX_DEGRADED, detail="cage unproven")
    regex = _regex(
        R,
        [
            _rule("corp_confidential_en", R, text="INTERNAL USE ONLY"),
            _rule("fp_template_placeholder", N, start=40, text="lorem ipsum"),
        ],
    )
    v = aggregate(fc, regex, _presidio(N))
    assert v.tier is C
    assert v.review_flags == ()


def test_flag_and_short_circuit_coexist_at_classified() -> None:
    # A CLASSIFIED tier driven by the FP-prone banner_en + a counter-signal:
    # flag raised, but consult_llm stays False (already at the top tier).
    regex = _regex(
        C,
        [
            _rule("banner_en", C, start=0, text="CONFIDENTIAL"),
            _rule("fp_creative_works", N, start=40, text="episode 5"),
        ],
    )
    v = aggregate(_extract(), regex, _presidio(N))
    assert v.tier is C
    assert v.consult_llm is False
    assert len(v.review_flags) == 1


# ── metadata floor — escalate-only (slice 9) ────────────────────────────────-


def test_metadata_floor_escalates_on_empty_body() -> None:
    # The §0 gap we are closing: a banner hidden in XMP keywords on a doc whose
    # body extracted NORMAL must still escalate the tier.
    v = aggregate(_extract(text=""), _regex(N), _presidio(N), meta_regex=_regex(C))
    assert v.tier is C
    stages = [p.stage for p in v.provenance]
    assert stages == ["extraction", "regex", "presidio", "metadata"]
    meta_prov = next(p for p in v.provenance if p.stage == "metadata")
    assert meta_prov.tier_floor is C
    assert meta_prov.version == "v3"


def test_metadata_floor_never_lowers_tier() -> None:
    # Metadata enters only via MAX — a benign metadata floor cannot pull a
    # CLASSIFIED body back down.
    v = aggregate(_extract(), _regex(C), _presidio(N), meta_regex=_regex(N))
    assert v.tier is C


def test_metadata_floor_takes_max_with_body() -> None:
    v = aggregate(_extract(), _regex(R), _presidio(N), meta_regex=_regex(R))
    assert v.tier is R
    v2 = aggregate(_extract(), _regex(R), _presidio(N), meta_regex=_regex(C))
    assert v2.tier is C


def test_metadata_driven_tier_is_not_a_counter_signal_candidate() -> None:
    # A counter-signal + FP-prone marking in the BODY does not make a
    # metadata-driven tier a demotion candidate: the tier-driving floor came from
    # metadata, so no body rule sits at the tier and no flag is raised.
    regex = _regex(
        R,
        [
            _rule("corp_confidential_en", R, start=0, text="INTERNAL USE ONLY"),
            _rule("fp_template_placeholder", N, start=40, text="lorem ipsum"),
        ],
    )
    v = aggregate(_extract(), regex, _presidio(N), meta_regex=_regex(C))
    assert v.tier is C
    assert v.review_flags == ()


def test_metadata_none_keeps_three_stage_provenance() -> None:
    v = aggregate(_extract(), _regex(R), _presidio(N))
    assert [p.stage for p in v.provenance] == ["extraction", "regex", "presidio"]


# ── provenance + determinism ────────────────────────────────────────────────-


def test_provenance_shape() -> None:
    v = aggregate(_extract(), _regex(R), _presidio(N))
    stages = [p.stage for p in v.provenance]
    assert stages == ["extraction", "regex", "presidio"]
    regex_prov = v.provenance[1]
    assert regex_prov.tier_floor is R
    assert regex_prov.version == "v3"
    assert v.provenance[2].version == "v1"


def test_deterministic() -> None:
    regex = _regex(R, [_rule("corp_confidential_en", R, text="INTERNAL USE ONLY")])
    args = (_extract(), regex, _presidio(N))
    assert aggregate(*args) == aggregate(*args)


def test_redacted_masks_sub_verdicts_and_preserves_original() -> None:
    regex = _regex(R, [_rule("pii_us_ssn", R, text="123-45-6789")])
    presidio = _presidio(R, [_pmatch("EMAIL_ADDRESS", R)])
    v = aggregate(_extract(), regex, presidio)
    red = v.redacted()
    assert red.regex.matches[0].matched_text == "*******6789"
    assert red.presidio.matches[0].matched_text != "Juan"
    # original untouched (frozen dataclasses + replace)
    assert v.regex.matches[0].matched_text == "123-45-6789"
    assert v.presidio.matches[0].matched_text == "Juan"
    assert red.tier is v.tier
