"""Shape tests for the §4.7 RedactionMarker."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import RedactionMarker, SensitivityTier

pytestmark = pytest.mark.contract


def test_redaction_marker_happy() -> None:
    m = RedactionMarker(
        tier=SensitivityTier.CLASSIFIED,
        reason="missing scope read:classified",
        request_clearance_at="/v1/auth/me",
        grant_request_subject="evidence_access",
    )
    assert m.redacted is True
    assert m.tier is SensitivityTier.CLASSIFIED


def test_redaction_marker_redacted_must_be_true() -> None:
    """The `redacted` field is a Literal[True] — anything else fails."""
    with pytest.raises(PydanticValidationError):
        RedactionMarker.model_validate(
            {"redacted": False, "tier": "classified", "reason": "x"},
        )


def test_redaction_marker_rejects_extra() -> None:
    with pytest.raises(PydanticValidationError):
        RedactionMarker.model_validate(
            {
                "tier": "restricted",
                "reason": "x",
                "rogue": "y",
            }
        )


@pytest.mark.parametrize("tier", list(SensitivityTier))
def test_redaction_marker_every_tier(tier: SensitivityTier) -> None:
    m = RedactionMarker(tier=tier, reason="missing scope")
    assert m.tier is tier
