"""AdvisorySchema: the structured-output contract + its JSON Schema export."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from eyenet.classifier.llm._schema import AdvisorySchema, advisory_json_schema

pytestmark = pytest.mark.unit


def test_json_schema_exposes_tier_and_confidence_enums() -> None:
    blob = json.dumps(advisory_json_schema())
    for value in ("normal", "restricted", "classified", "low", "medium", "high"):
        assert value in blob


def test_json_schema_forbids_extra_properties() -> None:
    assert advisory_json_schema()["additionalProperties"] is False


def test_valid_payload_validates() -> None:
    model = AdvisorySchema.model_validate(
        {"suggested_tier": "restricted", "summary": "s", "indicators": ["a"], "confidence": "high"}
    )
    assert model.suggested_tier == "restricted"


def test_extra_key_is_rejected_by_the_contract() -> None:
    with pytest.raises(ValidationError):
        AdvisorySchema.model_validate(
            {"suggested_tier": "normal", "summary": "s", "confidence": "low", "rogue": 1}
        )


def test_bad_tier_rejected_by_the_contract() -> None:
    with pytest.raises(ValidationError):
        AdvisorySchema.model_validate(
            {"suggested_tier": "ultra", "summary": "s", "confidence": "low"}
        )
