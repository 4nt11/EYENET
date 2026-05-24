"""Shape tests for §4.10 case-management schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import (
    CaseArchiveRequest,
    CaseCloseRequest,
    CaseCollaboratorAddRequest,
    CaseCollaboratorRevokeRequest,
    CaseCollaboratorSummary,
    CaseCreateRequest,
    CaseDetail,
    CaseMemberAddRequest,
    CaseMemberBulkAddRequest,
    CaseMemberBulkRemoveRequest,
    CaseMemberBulkResult,
    CaseMemberRemoveRequest,
    CaseMemberSubjectRef,
    CaseMemberSummary,
    CaseReopenRequest,
    CaseRoleOnCase,
    CaseStatus,
    CaseSubjectKind,
    CaseSummary,
    CaseUpdateRequest,
    CursorPageCaseCollaboratorSummary,
    CursorPageCaseMemberSummary,
    CursorPageCaseSummary,
    SensitivityTier,
)

pytestmark = pytest.mark.contract


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def uid() -> UUID:
    return UUID("01906f00-0000-7000-8000-000000000001")


@pytest.fixture
def uid2() -> UUID:
    return UUID("01906f00-0000-7000-8000-000000000002")


# --- CaseSummary / CaseDetail -----------------------------------------------


@pytest.mark.parametrize("status", list(CaseStatus))
@pytest.mark.parametrize("tier", list(SensitivityTier))
def test_case_summary_every_status_and_tier(
    uid: UUID,
    now: datetime,
    status: CaseStatus,
    tier: SensitivityTier,
) -> None:
    s = CaseSummary(
        case_id=uid,
        title="APT-29 Q2 recruitment",
        status=status,
        effective_tier=tier,
        created_by_user_id=uid,
        created_at=now,
    )
    assert s.status is status
    assert s.effective_tier is tier
    assert s.member_count is None


def test_case_summary_rejects_short_title(uid: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        CaseSummary(
            case_id=uid,
            title="oh",
            status=CaseStatus.OPEN,
            effective_tier=SensitivityTier.NORMAL,
            created_by_user_id=uid,
            created_at=now,
        )


def test_case_summary_rejects_extra(uid: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        CaseSummary.model_validate(
            {
                "case_id": str(uid),
                "title": "APT-29 Q2 recruitment",
                "status": "open",
                "effective_tier": "normal",
                "created_by_user_id": str(uid),
                "created_at": now.isoformat(),
                "rogue": "x",
            }
        )


def test_case_detail_extends_summary(uid: UUID, uid2: UUID, now: datetime) -> None:
    d = CaseDetail(
        case_id=uid,
        title="APT-29 Q2 recruitment",
        status=CaseStatus.CLOSED,
        effective_tier=SensitivityTier.CLASSIFIED,
        created_by_user_id=uid,
        created_at=now,
        description="long-running investigation",
        closed_at=now,
        closed_by_user_id=uid2,
        close_reason="investigation concluded, evidence archived for legal review",
        parent_case_id=uid2,
    )
    assert d.parent_case_id == uid2
    assert d.archived_at is None


# --- CaseCreateRequest ------------------------------------------------------


def test_case_create_happy() -> None:
    req = CaseCreateRequest(title="APT-29 Q2 recruitment")
    assert req.description is None


def test_case_create_rejects_short_title() -> None:
    with pytest.raises(PydanticValidationError):
        CaseCreateRequest(title="x")


def test_case_create_rejects_extra() -> None:
    with pytest.raises(PydanticValidationError):
        CaseCreateRequest.model_validate(
            {
                "title": "APT-29 Q2 recruitment",
                "rogue": "x",
            }
        )


# --- CaseUpdateRequest ------------------------------------------------------


def test_case_update_reason_required() -> None:
    with pytest.raises(PydanticValidationError):
        CaseUpdateRequest(title="renamed case")  # type: ignore[call-arg]


def test_case_update_reason_min_length() -> None:
    with pytest.raises(PydanticValidationError):
        CaseUpdateRequest(title="renamed case", reason="ok")


def test_case_update_happy() -> None:
    req = CaseUpdateRequest(
        description="updated scope after week 3 review",
        reason="adding context after weekly review session",
    )
    assert req.title is None


# --- Close / Reopen / Archive ----------------------------------------------


def test_close_request_min_length() -> None:
    with pytest.raises(PydanticValidationError):
        CaseCloseRequest(close_reason="ok")


def test_close_request_happy() -> None:
    r = CaseCloseRequest(close_reason="investigation concluded, evidence preserved")
    assert r.close_reason.startswith("invest")


def test_reopen_request_min_length() -> None:
    with pytest.raises(PydanticValidationError):
        CaseReopenRequest(reopen_reason="ok")


def test_archive_request_requires_32_chars() -> None:
    """§4.10.3 archive bar — reason ≥ 32 chars."""
    with pytest.raises(PydanticValidationError):
        CaseArchiveRequest(archive_reason="too short for archive bar")


def test_archive_request_happy() -> None:
    r = CaseArchiveRequest(
        archive_reason="legal review complete, evidence frozen for compliance retention",
    )
    assert len(r.archive_reason) >= 32


# --- Member shapes ----------------------------------------------------------


@pytest.mark.parametrize("kind", list(CaseSubjectKind))
def test_member_summary_every_subject_kind(uid: UUID, now: datetime, kind: CaseSubjectKind) -> None:
    m = CaseMemberSummary(
        member_id=uid,
        case_id=uid,
        subject_kind=kind,
        subject_id=uid,
        added_by_user_id=uid,
        added_at=now,
        add_reason="initial evidence intake from collector pass 3",
        active=True,
    )
    assert m.subject_kind is kind


def test_member_summary_inactive_carries_removal_fields(
    uid: UUID, uid2: UUID, now: datetime
) -> None:
    m = CaseMemberSummary(
        member_id=uid,
        case_id=uid,
        subject_kind=CaseSubjectKind.ATTACHMENT,
        subject_id=uid,
        added_by_user_id=uid,
        added_at=now,
        add_reason="initial evidence intake from collector pass 3",
        active=False,
        removed_at=now,
        removed_by_user_id=uid2,
        removal_reason="duplicate of member abc-123, consolidated",
    )
    assert m.active is False
    assert m.removed_by_user_id == uid2


def test_member_add_min_reason(uid: UUID) -> None:
    with pytest.raises(PydanticValidationError):
        CaseMemberAddRequest(
            subject_kind=CaseSubjectKind.OBSERVATION,
            subject_id=uid,
            add_reason="ok",
        )


def test_member_remove_min_reason() -> None:
    with pytest.raises(PydanticValidationError):
        CaseMemberRemoveRequest(removal_reason="ok")


# --- Bulk member shapes ----------------------------------------------------


def test_bulk_add_requires_at_least_one_subject() -> None:
    with pytest.raises(PydanticValidationError):
        CaseMemberBulkAddRequest(
            subjects=[],
            add_reason="initial evidence intake from collector pass 3",
        )


def test_bulk_add_caps_at_500(uid: UUID) -> None:
    subjects = [
        CaseMemberSubjectRef(subject_kind=CaseSubjectKind.OBSERVATION, subject_id=uid)
        for _ in range(501)
    ]
    with pytest.raises(PydanticValidationError):
        CaseMemberBulkAddRequest(
            subjects=subjects,
            add_reason="initial evidence intake from collector pass 3",
        )


def test_bulk_add_happy(uid: UUID, uid2: UUID) -> None:
    req = CaseMemberBulkAddRequest(
        subjects=[
            CaseMemberSubjectRef(subject_kind=CaseSubjectKind.OBSERVATION, subject_id=uid),
            CaseMemberSubjectRef(subject_kind=CaseSubjectKind.ATTACHMENT, subject_id=uid2),
        ],
        add_reason="initial evidence intake from collector pass 3",
    )
    assert len(req.subjects) == 2


def test_bulk_remove_requires_at_least_one_id() -> None:
    with pytest.raises(PydanticValidationError):
        CaseMemberBulkRemoveRequest(
            member_ids=[],
            removal_reason="cleanup before case close",
        )


def test_bulk_remove_happy(uid: UUID, uid2: UUID) -> None:
    req = CaseMemberBulkRemoveRequest(
        member_ids=[uid, uid2],
        removal_reason="cleanup before case close",
    )
    assert len(req.member_ids) == 2


def test_bulk_result_carries_tiers(uid: UUID, uid2: UUID) -> None:
    res = CaseMemberBulkResult(
        case_id=uid,
        affected_member_ids=[uid, uid2],
        audit_event_ids=[uid, uid2],
        effective_tier=SensitivityTier.CLASSIFIED,
        prior_effective_tier=SensitivityTier.RESTRICTED,
    )
    assert res.effective_tier is SensitivityTier.CLASSIFIED


# --- Collaborator shapes ----------------------------------------------------


@pytest.mark.parametrize("role", list(CaseRoleOnCase))
def test_collaborator_summary_every_role(
    uid: UUID,
    now: datetime,
    role: CaseRoleOnCase,
) -> None:
    c = CaseCollaboratorSummary(
        collaborator_id=uid,
        case_id=uid,
        user_id=uid,
        role_on_case=role,
        granted_by_user_id=uid,
        granted_at=now,
        active=True,
    )
    assert c.role_on_case is role


def test_collaborator_add_happy(uid: UUID) -> None:
    req = CaseCollaboratorAddRequest(user_id=uid, role_on_case=CaseRoleOnCase.ANALYST)
    assert req.role_on_case is CaseRoleOnCase.ANALYST


def test_collaborator_revoke_requires_reason() -> None:
    with pytest.raises(PydanticValidationError):
        CaseCollaboratorRevokeRequest(revocation_reason="")


# --- Cursor pages -----------------------------------------------------------


def test_cursor_page_case_summary_empty() -> None:
    page = CursorPageCaseSummary()
    assert page.items == []


def test_cursor_page_case_member_empty() -> None:
    page = CursorPageCaseMemberSummary()
    assert page.next_cursor is None


def test_cursor_page_case_collaborator_rejects_extra() -> None:
    with pytest.raises(PydanticValidationError):
        CursorPageCaseCollaboratorSummary.model_validate({"items": [], "rogue": "x"})


# --- case_refs added to existing schemas -----------------------------------


def test_clearance_grant_request_carries_case_refs(uid: UUID, uid2: UUID, now: datetime) -> None:
    from eyenet.api.v1.schemas import ClearanceGrantRequest, ClearanceScope

    req = ClearanceGrantRequest(
        user_id=uid,
        scope=ClearanceScope.READ_CLASSIFIED,
        reason="case=APT-29 peer-reviewed",
        expires_at=now,
        case_refs=[uid2],
    )
    assert req.case_refs == [uid2]


def test_reclassification_request_carries_case_refs(uid: UUID) -> None:
    from eyenet.api.v1.schemas import ReclassificationRequest

    sig = "ed25519:" + "A" * 88
    req = ReclassificationRequest(
        new_tier=SensitivityTier.CLASSIFIED,
        reason="case=APT-29 batch 3 peer-reviewed by bob; promotion required",
        operator_signature=sig,
        case_refs=[uid],
    )
    assert req.case_refs == [uid]


def test_file_access_acknowledgment_carries_case_refs(uid: UUID, uid2: UUID) -> None:
    from eyenet.api.v1.schemas import FileAccessAcknowledgment

    sig = "ed25519:" + "A" * 88
    ack = FileAccessAcknowledgment(
        access_nonce=uid,
        expected_content_hash="0" * 64,
        reason="case=APT-29 routine review",
        operator_signature=sig,
        case_refs=[uid2],
    )
    assert ack.case_refs == [uid2]
