"""classification_audit_payload(): JSON-safe, redacted, full provenance."""

from __future__ import annotations

import json

import pytest

from eyenet.classifier.aggregate import aggregate, classification_audit_payload
from eyenet.classifier.presidio._types import PresidioMatch, PresidioVerdict
from eyenet.classifier.ruleset._types import RegexVerdict, RuleMatch
from eyenet.classifier.sandbox import ExtractResult, FailedClosed, FailReason
from eyenet.contracts.enums import SensitivityTier

pytestmark = pytest.mark.unit

R = SensitivityTier.RESTRICTED
C = SensitivityTier.CLASSIFIED
N = SensitivityTier.NORMAL


def _extract() -> ExtractResult:
    return ExtractResult(text="x", meta={"doc_kind": "pdf", "empty": False, "ocr_applied": False})


def _verdict_with_raw_spans() -> object:
    regex = RegexVerdict(
        tier_floor=R,
        matches=(
            RuleMatch(
                rule_name="pii_us_ssn", tier_floor=R, start=0, end=11, matched_text="123-45-6789"
            ),
        ),
        ruleset_version="v3",
    )
    presidio = PresidioVerdict(
        tier_floor=R,
        matches=(
            PresidioMatch(
                entity_type="EMAIL_ADDRESS",
                tier_floor=R,
                start=20,
                end=40,
                score=0.95,
                language="es",
                matched_text="juan.perez@example.net",
            ),
        ),
        map_version="v1",
    )
    return aggregate(_extract(), regex, presidio)


def test_payload_is_json_serializable() -> None:
    payload = classification_audit_payload(_verdict_with_raw_spans())
    # round-trips through json with no custom encoder
    assert json.loads(json.dumps(payload))["tier"] == "restricted"


def test_payload_carries_floors_versions_and_final_tier() -> None:
    payload = classification_audit_payload(_verdict_with_raw_spans())
    assert payload["tier"] == "restricted"
    assert payload["ruleset_version"] == "v3"
    assert payload["pii_map_version"] == "v1"
    assert payload["consult_llm"] is True
    stages = {p["stage"]: p for p in payload["provenance"]}  # type: ignore[union-attr]
    assert set(stages) == {"extraction", "regex", "presidio"}
    assert stages["regex"]["tier_floor"] == "restricted"


def test_payload_never_leaks_raw_matched_text() -> None:
    payload = classification_audit_payload(_verdict_with_raw_spans())
    blob = json.dumps(payload)
    assert "123-45-6789" not in blob  # SSN masked
    assert "juan.perez@example.net" not in blob  # email masked
    # the masked tails survive as provenance
    regex_match = payload["regex_matches"][0]  # type: ignore[index]
    assert regex_match["matched_text"].endswith("6789")
    assert regex_match["rule"] == "pii_us_ssn"


def test_review_flags_serialized() -> None:
    # FP-prone tier driver + counter-signal → one review flag in the payload.
    regex = RegexVerdict(
        tier_floor=R,
        matches=(
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
        ),
        ruleset_version="v3",
    )
    presidio = PresidioVerdict(tier_floor=N, matches=(), map_version="v1")
    payload = classification_audit_payload(aggregate(_extract(), regex, presidio))
    flags = payload["review_flags"]
    assert len(flags) == 1  # type: ignore[arg-type]
    assert flags[0]["kind"] == "possible_over_classification"  # type: ignore[index]
    assert flags[0]["suggested_tier"] == "normal"  # type: ignore[index]
    assert flags[0]["corroborated"] is False  # type: ignore[index]  # no LLM ran here


def test_fail_closed_payload_shape() -> None:
    fc = FailedClosed(reason=FailReason.PARSER_KILLED, detail="SIGSYS")
    regex = RegexVerdict(tier_floor=N, matches=(), ruleset_version="v3")
    presidio = PresidioVerdict(tier_floor=N, matches=(), map_version="v1")
    payload = classification_audit_payload(aggregate(fc, regex, presidio))
    assert payload["tier"] == "classified"
    assert payload["fail_closed"] is True
    assert payload["consult_llm"] is False
    ext = next(p for p in payload["provenance"] if p["stage"] == "extraction")  # type: ignore[union-attr,index]
    assert ext["fail_closed"] is True
    assert ext["version"] == "parser_killed"
