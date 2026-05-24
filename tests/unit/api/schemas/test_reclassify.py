"""Shape tests for §4.9 reclassification schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import (
    ReclassificationRequest,
    ReclassificationResult,
    ReclassificationSubjectKind,
    SensitivityTier,
)

pytestmark = pytest.mark.contract

_SIG = "ed25519:" + "A" * 88
_REASON = "case=APT-29 batch 3 peer-reviewed by bob; promotion required"  # ≥ 32 chars


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def uid() -> UUID:
    return UUID("01906f00-0000-7000-8000-000000000001")


@pytest.fixture
def uid2() -> UUID:
    return UUID("01906f00-0000-7000-8000-000000000002")


# --- ReclassificationRequest ------------------------------------------------


@pytest.mark.parametrize("tier", [SensitivityTier.RESTRICTED, SensitivityTier.CLASSIFIED])
def test_request_happy(tier: SensitivityTier) -> None:
    req = ReclassificationRequest(
        new_tier=tier,
        reason=_REASON,
        operator_signature=_SIG,
    )
    assert req.new_tier is tier
    assert req.viewing_context is None


def test_request_viewing_context_optional() -> None:
    req = ReclassificationRequest(
        new_tier=SensitivityTier.CLASSIFIED,
        reason=_REASON,
        viewing_context="reviewing case=APT-29 evidence batch 3",
        operator_signature=_SIG,
    )
    assert req.viewing_context is not None


def test_request_reason_too_short() -> None:
    with pytest.raises(PydanticValidationError):
        ReclassificationRequest(
            new_tier=SensitivityTier.RESTRICTED,
            reason="short reason",
            operator_signature=_SIG,
        )


def test_request_signature_pattern_enforced() -> None:
    with pytest.raises(PydanticValidationError):
        ReclassificationRequest(
            new_tier=SensitivityTier.RESTRICTED,
            reason=_REASON,
            operator_signature="hmac:not-an-ed25519-sig",
        )


def test_request_rejects_extra() -> None:
    with pytest.raises(PydanticValidationError):
        ReclassificationRequest.model_validate(
            {
                "new_tier": "restricted",
                "reason": _REASON,
                "operator_signature": _SIG,
                "rogue": "x",
            }
        )


def test_request_accepts_normal_tier_shape_but_server_must_reject() -> None:
    """Pydantic accepts any SensitivityTier value; the endpoint guard rejects
    `normal` per §4.9 (cannot reclassify TO normal). Wire-shape only here."""
    req = ReclassificationRequest(
        new_tier=SensitivityTier.NORMAL,
        reason=_REASON,
        operator_signature=_SIG,
    )
    assert req.new_tier is SensitivityTier.NORMAL


# --- ReclassificationResult -------------------------------------------------


@pytest.mark.parametrize("kind", list(ReclassificationSubjectKind))
def test_result_every_subject_kind(
    uid: UUID, uid2: UUID, now: datetime, kind: ReclassificationSubjectKind
) -> None:
    res = ReclassificationResult(
        subject_id=uid,
        subject_kind=kind,
        classifier_tier=SensitivityTier.NORMAL,
        operator_tier_override=SensitivityTier.CLASSIFIED,
        effective_tier=SensitivityTier.CLASSIFIED,
        prior_effective_tier=SensitivityTier.NORMAL,
        audit_event_id=uid2,
        reclassified_at=now,
        grant_id=uid2,
    )
    assert res.subject_kind is kind


def test_result_rejects_extra(uid: UUID, uid2: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        ReclassificationResult.model_validate(
            {
                "subject_id": str(uid),
                "subject_kind": "observation",
                "classifier_tier": "normal",
                "operator_tier_override": "restricted",
                "effective_tier": "restricted",
                "prior_effective_tier": "normal",
                "audit_event_id": str(uid2),
                "reclassified_at": now.isoformat(),
                "grant_id": str(uid2),
                "rogue": "x",
            }
        )


def test_result_requires_grant_id(uid: UUID, uid2: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        ReclassificationResult(
            subject_id=uid,
            subject_kind=ReclassificationSubjectKind.ATTACHMENT,
            classifier_tier=SensitivityTier.NORMAL,
            operator_tier_override=SensitivityTier.RESTRICTED,
            effective_tier=SensitivityTier.RESTRICTED,
            prior_effective_tier=SensitivityTier.NORMAL,
            audit_event_id=uid2,
            reclassified_at=now,
        )  # type: ignore[call-arg]


def test_result_rejects_unknown_subject_kind(uid: UUID, uid2: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        ReclassificationResult.model_validate(
            {
                "subject_id": str(uid),
                "subject_kind": "case_tag",
                "classifier_tier": "normal",
                "operator_tier_override": "restricted",
                "effective_tier": "restricted",
                "prior_effective_tier": "normal",
                "audit_event_id": str(uid2),
                "reclassified_at": now.isoformat(),
                "grant_id": str(uid2),
            }
        )
