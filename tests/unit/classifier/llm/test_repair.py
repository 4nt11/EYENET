"""parse_advisory(): the dumb-LLM body-check — repair, coerce, sanitize, refuse.

Pure; no provider. Covers the JSON-extraction repair, defensive coercion of
every field, sanitization of free text, and the refuse-not-guess discipline for
an unknown/missing tier.
"""

from __future__ import annotations

import pytest

from eyenet.classifier.llm import LlmAdvisory, LlmConfig, RepairError, parse_advisory
from eyenet.contracts.enums import SensitivityTier

pytestmark = pytest.mark.unit

R = SensitivityTier.RESTRICTED
C = SensitivityTier.CLASSIFIED
N = SensitivityTier.NORMAL


def _cfg(**over: object) -> LlmConfig:
    base: dict[str, object] = {
        "config_version": "t",
        "model": "m",
        "endpoint": "http://127.0.0.1:11434",
        "connect_timeout_s": 1.0,
        "request_timeout_s": 1.0,
        "max_attempts": 3,
        "max_text_chars": 1000,
        "max_summary_chars": 200,
        "max_indicators": 3,
        "allow_remote": False,
    }
    base.update(over)
    return LlmConfig(**base)  # type: ignore[arg-type]


_GOOD = (
    '{"suggested_tier": "restricted", "summary": "A memo", '
    '"indicators": ["x", "y"], "confidence": "high"}'
)


def test_clean_object_parses() -> None:
    adv = parse_advisory(_GOOD, cfg=_cfg())
    assert isinstance(adv, LlmAdvisory)
    assert adv.suggested_tier is R
    assert adv.confidence == "high"
    assert adv.indicators == ("x", "y")
    assert adv.summary == "A memo"
    # Orchestration fields stay at defaults — advise() fills them.
    assert adv.model == ""
    assert adv.attempts == 1
    assert adv.truncated_input is False


def test_markdown_fenced_json_parses() -> None:
    adv = parse_advisory(f"```json\n{_GOOD}\n```", cfg=_cfg())
    assert isinstance(adv, LlmAdvisory)
    assert adv.suggested_tier is R


def test_prose_wrapped_json_parses() -> None:
    adv = parse_advisory(f"Sure, here you go:\n{_GOOD}\nHope that helps!", cfg=_cfg())
    assert isinstance(adv, LlmAdvisory)


def test_trailing_garbage_after_object_ignored() -> None:
    adv = parse_advisory(f"{_GOOD} and then some junk {{oops", cfg=_cfg())
    assert isinstance(adv, LlmAdvisory)
    assert adv.suggested_tier is R


def test_tier_is_case_insensitive() -> None:
    adv = parse_advisory(
        '{"suggested_tier": "CLASSIFIED", "summary": "s", "confidence": "low"}', cfg=_cfg()
    )
    assert isinstance(adv, LlmAdvisory)
    assert adv.suggested_tier is C


def test_no_json_object_is_repair_error() -> None:
    out = parse_advisory("I cannot help with that.", cfg=_cfg())
    assert isinstance(out, RepairError)
    assert out.reason == "no_json_object"


def test_missing_tier_is_repair_error() -> None:
    out = parse_advisory('{"summary": "s", "confidence": "low"}', cfg=_cfg())
    assert isinstance(out, RepairError)
    assert out.reason == "missing_suggested_tier"


def test_non_string_tier_is_repair_error() -> None:
    out = parse_advisory('{"suggested_tier": 5, "summary": "s"}', cfg=_cfg())
    assert isinstance(out, RepairError)
    assert out.reason == "missing_suggested_tier"


def test_unknown_tier_refuses_never_guesses() -> None:
    out = parse_advisory(
        '{"suggested_tier": "ultrasecret", "summary": "s", "confidence": "low"}', cfg=_cfg()
    )
    assert isinstance(out, RepairError)
    assert out.reason.startswith("unknown_tier:")


def test_extra_keys_ignored_and_model_not_taken_from_output() -> None:
    raw = (
        '{"suggested_tier": "normal", "summary": "s", "confidence": "low", '
        '"bonus": 1, "model": "EVIL"}'
    )
    adv = parse_advisory(raw, cfg=_cfg())
    assert isinstance(adv, LlmAdvisory)
    assert adv.model == ""  # provider-reported, never trusted from output


def test_indicators_string_is_wrapped() -> None:
    adv = parse_advisory(
        '{"suggested_tier": "normal", "summary": "s", "indicators": "solo", "confidence": "low"}',
        cfg=_cfg(),
    )
    assert isinstance(adv, LlmAdvisory)
    assert adv.indicators == ("solo",)


def test_indicators_capped_to_max() -> None:
    raw = (
        '{"suggested_tier": "normal", "summary": "s", '
        '"indicators": ["a","b","c","d","e"], "confidence": "low"}'
    )
    adv = parse_advisory(raw, cfg=_cfg(max_indicators=3))
    assert isinstance(adv, LlmAdvisory)
    assert len(adv.indicators) == 3


def test_invalid_confidence_defaults_low() -> None:
    adv = parse_advisory(
        '{"suggested_tier": "normal", "summary": "s", "confidence": "banana"}', cfg=_cfg()
    )
    assert isinstance(adv, LlmAdvisory)
    assert adv.confidence == "low"


def test_missing_confidence_defaults_low() -> None:
    adv = parse_advisory('{"suggested_tier": "normal", "summary": "s"}', cfg=_cfg())
    assert isinstance(adv, LlmAdvisory)
    assert adv.confidence == "low"


def test_summary_is_sanitized() -> None:
    raw = '{"suggested_tier": "normal", "summary": "<script>x</script>", "confidence": "low"}'
    adv = parse_advisory(raw, cfg=_cfg())
    assert isinstance(adv, LlmAdvisory)
    assert "<script>" not in adv.summary
    assert "&lt;script&gt;" in adv.summary


def test_nested_braces_are_balanced_correctly() -> None:
    raw = '{"suggested_tier": "normal", "summary": "s", "confidence": "low", "meta": {"k": "v"}}'
    adv = parse_advisory(raw, cfg=_cfg())
    assert isinstance(adv, LlmAdvisory)
    assert adv.suggested_tier is N


def test_escaped_quotes_inside_strings_do_not_break_scan() -> None:
    raw = r'{"suggested_tier": "normal", "summary": "a \"quoted\" word", "confidence": "low"}'
    adv = parse_advisory(raw, cfg=_cfg())
    assert isinstance(adv, LlmAdvisory)
    assert "quoted" in adv.summary


def test_unclosed_object_is_repair_error() -> None:
    out = parse_advisory('{"suggested_tier": "normal", "summary": "s"', cfg=_cfg())
    assert isinstance(out, RepairError)
    assert out.reason == "no_json_object"


def test_balanced_but_invalid_json_is_repair_error() -> None:
    out = parse_advisory("{not: valid, json}", cfg=_cfg())
    assert isinstance(out, RepairError)
    assert out.reason == "no_json_object"


def test_non_string_fields_are_coerced() -> None:
    raw = '{"suggested_tier": "normal", "summary": 123, "indicators": [7], "confidence": "low"}'
    adv = parse_advisory(raw, cfg=_cfg())
    assert isinstance(adv, LlmAdvisory)
    assert adv.summary == "123"
    assert adv.indicators == ("7",)
