"""Schema-level tests for case_v2 / case_member / case_collaborator (§4.10)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from eyenet.contracts.enums import (
    CaseRoleOnCase,
    CaseStatus,
    CaseSubjectKind,
    SensitivityTier,
)
from eyenet.models.case import CaseCollaboratorTable, CaseMemberTable, CaseTable
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository  # noqa: F401

_NOW = datetime(2026, 5, 24, tzinfo=UTC)
_REASON = "initial evidence intake from collector pass 1"


@pytest.fixture
def session() -> Session:
    import os

    os.environ.setdefault("EYENET_STORAGE_TYPE", "sqlite")
    storage = get_repository(in_memory=True)
    return Session(storage.sync_engine)


def _case(session: Session, **overrides: object) -> UUID:
    defaults: dict[str, object] = {
        "title": "APT-29 Q2 recruitment",
        "created_by_user_id": uuid4(),
        "created_at": _NOW,
    }
    defaults.update(overrides)
    c = CaseTable(**defaults)  # type: ignore[arg-type]
    session.add(c)
    session.commit()
    session.refresh(c)
    return c.id


# --- CaseTable -------------------------------------------------------------


@pytest.mark.unit
def test_case_happy_path(session: Session) -> None:
    cid = _case(session)
    assert cid is not None


@pytest.mark.unit
def test_case_title_min_3_chars(session: Session) -> None:
    session.add(CaseTable(title="ab", created_by_user_id=uuid4(), created_at=_NOW))
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_case_close_triplet_partial_rejected(session: Session) -> None:
    session.add(
        CaseTable(
            title="Test case here",
            status=CaseStatus.CLOSED,
            created_by_user_id=uuid4(),
            created_at=_NOW,
            closed_at=_NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_case_close_triplet_complete_accepted(session: Session) -> None:
    session.add(
        CaseTable(
            title="Test case here",
            status=CaseStatus.CLOSED,
            created_by_user_id=uuid4(),
            created_at=_NOW,
            closed_at=_NOW,
            closed_by_user_id=uuid4(),
            close_reason="investigation concluded",
        )
    )
    session.commit()


@pytest.mark.unit
def test_case_archive_triplet_partial_rejected(session: Session) -> None:
    session.add(
        CaseTable(
            title="Test case here",
            status=CaseStatus.ARCHIVED,
            created_by_user_id=uuid4(),
            created_at=_NOW,
            archived_at=_NOW,
            archived_by_user_id=uuid4(),
            # missing archive_reason
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
@pytest.mark.parametrize("status", list(CaseStatus))
def test_every_case_status_round_trips(session: Session, status: CaseStatus) -> None:
    c = CaseTable(
        title="status round-trip",
        status=status,
        created_by_user_id=uuid4(),
        created_at=_NOW,
        # Triplets must be complete for CLOSED/ARCHIVED.
        closed_at=_NOW if status in (CaseStatus.CLOSED, CaseStatus.ARCHIVED) else None,
        closed_by_user_id=uuid4() if status in (CaseStatus.CLOSED, CaseStatus.ARCHIVED) else None,
        close_reason="closing for status round-trip"
        if status in (CaseStatus.CLOSED, CaseStatus.ARCHIVED)
        else None,
        archived_at=_NOW if status == CaseStatus.ARCHIVED else None,
        archived_by_user_id=uuid4() if status == CaseStatus.ARCHIVED else None,
        archive_reason="archiving for round-trip" if status == CaseStatus.ARCHIVED else None,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    assert c.status is status


# --- CaseMemberTable ------------------------------------------------------


@pytest.mark.unit
def test_member_add_reason_min_16_chars(session: Session) -> None:
    cid = _case(session)
    session.add(
        CaseMemberTable(
            case_id=cid,
            subject_kind=CaseSubjectKind.OBSERVATION,
            subject_id=uuid4(),
            added_by_user_id=uuid4(),
            added_at=_NOW,
            add_reason="too short",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
@pytest.mark.parametrize("kind", list(CaseSubjectKind))
def test_every_subject_kind_round_trips(session: Session, kind: CaseSubjectKind) -> None:
    cid = _case(session)
    m = CaseMemberTable(
        case_id=cid,
        subject_kind=kind,
        subject_id=uuid4(),
        added_by_user_id=uuid4(),
        added_at=_NOW,
        add_reason=_REASON,
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    assert m.subject_kind is kind


@pytest.mark.unit
def test_member_double_active_add_rejected(session: Session) -> None:
    """Partial unique on (case_id, subject_kind, subject_id) WHERE removed_at IS NULL."""
    cid = _case(session)
    sub_id = uuid4()
    for _ in range(2):
        session.add(
            CaseMemberTable(
                case_id=cid,
                subject_kind=CaseSubjectKind.OBSERVATION,
                subject_id=sub_id,
                added_by_user_id=uuid4(),
                added_at=_NOW,
                add_reason=_REASON,
            )
        )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_member_soft_delete_allows_readd(session: Session) -> None:
    """After removing a member, the same subject can be added back."""
    cid = _case(session)
    sub_id = uuid4()
    first = CaseMemberTable(
        case_id=cid,
        subject_kind=CaseSubjectKind.ATTACHMENT,
        subject_id=sub_id,
        added_by_user_id=uuid4(),
        added_at=_NOW,
        add_reason=_REASON,
    )
    session.add(first)
    session.commit()
    first.removed_at = _NOW
    first.removed_by_user_id = uuid4()
    first.removal_reason = "duplicate consolidated"
    session.add(first)
    session.commit()
    # Re-add — must succeed because the prior row's removed_at is set.
    session.add(
        CaseMemberTable(
            case_id=cid,
            subject_kind=CaseSubjectKind.ATTACHMENT,
            subject_id=sub_id,
            added_by_user_id=uuid4(),
            added_at=_NOW,
            add_reason="readding after consolidation review",
        )
    )
    session.commit()


@pytest.mark.unit
def test_member_remove_triplet_partial_rejected(session: Session) -> None:
    cid = _case(session)
    m = CaseMemberTable(
        case_id=cid,
        subject_kind=CaseSubjectKind.MESSAGE,
        subject_id=uuid4(),
        added_by_user_id=uuid4(),
        added_at=_NOW,
        add_reason=_REASON,
        removed_at=_NOW,  # missing removed_by_user_id and removal_reason
    )
    session.add(m)
    with pytest.raises(IntegrityError):
        session.commit()


# --- CaseCollaboratorTable ------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("role", list(CaseRoleOnCase))
def test_every_role_round_trips(session: Session, role: CaseRoleOnCase) -> None:
    cid = _case(session)
    c = CaseCollaboratorTable(
        case_id=cid,
        user_id=uuid4(),
        role_on_case=role,
        granted_by_user_id=uuid4(),
        granted_at=_NOW,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    assert c.role_on_case is role


@pytest.mark.unit
def test_collaborator_double_active_rejected(session: Session) -> None:
    cid = _case(session)
    user_id = uuid4()
    for _ in range(2):
        session.add(
            CaseCollaboratorTable(
                case_id=cid,
                user_id=user_id,
                role_on_case=CaseRoleOnCase.ANALYST,
                granted_by_user_id=uuid4(),
                granted_at=_NOW,
            )
        )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_collaborator_revoke_triplet_partial_rejected(session: Session) -> None:
    cid = _case(session)
    c = CaseCollaboratorTable(
        case_id=cid,
        user_id=uuid4(),
        role_on_case=CaseRoleOnCase.REVIEWER,
        granted_by_user_id=uuid4(),
        granted_at=_NOW,
        revoked_at=_NOW,  # missing two of the triplet
    )
    session.add(c)
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_case_default_effective_tier_is_normal(session: Session) -> None:
    """Materialised tier defaults to normal; recompute is the helper's job (later commit)."""
    cid = _case(session)
    c = session.get(CaseTable, cid)
    assert c is not None
    assert c.effective_tier is SensitivityTier.NORMAL
