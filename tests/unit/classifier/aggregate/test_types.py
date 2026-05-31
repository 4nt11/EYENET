"""Aggregator value types: frozen, hashable, well-shaped."""

from __future__ import annotations

import dataclasses

import pytest

from eyenet.classifier.aggregate import ReviewFlag, ReviewKind, StageProvenance
from eyenet.contracts.enums import SensitivityTier

pytestmark = pytest.mark.unit


def test_review_flag_frozen_and_hashable() -> None:
    flag = ReviewFlag(
        kind=ReviewKind.POSSIBLE_OVER_CLASSIFICATION,
        detail="counter-signal co-occurrence",
        suggested_tier=SensitivityTier.NORMAL,
    )
    assert {flag}  # hashable
    with pytest.raises(dataclasses.FrozenInstanceError):
        flag.detail = "mutated"  # type: ignore[misc]


def test_review_flag_default_suggested_tier_is_none() -> None:
    flag = ReviewFlag(kind=ReviewKind.LLM_HIGHER_TIER, detail="advisory")
    assert flag.suggested_tier is None


def test_stage_provenance_defaults() -> None:
    prov = StageProvenance(stage="regex", tier_floor=SensitivityTier.RESTRICTED, version="v3")
    assert prov.fail_closed is False
    assert prov.detail == ""
    assert {prov}  # hashable


def test_review_kind_values() -> None:
    assert ReviewKind.POSSIBLE_OVER_CLASSIFICATION.value == "possible_over_classification"
    assert ReviewKind.LLM_HIGHER_TIER.value == "llm_higher_tier"
