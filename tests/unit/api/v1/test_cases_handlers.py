# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the /v1/cases CRUD handlers (Slice B, §4.10).

Bypasses ASGI routing (coverage can't trace it) — RequireScope is exercised in
the integration suite. These credit the handler bodies + the in-handler
authorization gates (require_case_visible / require_owner_or_admin_case).
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest

from eyenet.api.deps import ConflictError, CurrentUser, ResourceNotFound, ScopeForbidden
from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.cases.api_add_collaborator import cases_add_collaborator
from eyenet.api.v1.cases.api_add_member import cases_add_member
from eyenet.api.v1.cases.api_archive_case import cases_archive
from eyenet.api.v1.cases.api_bulk_add_members import cases_bulk_add_members
from eyenet.api.v1.cases.api_bulk_remove_members import cases_bulk_remove_members
from eyenet.api.v1.cases.api_close_case import cases_close
from eyenet.api.v1.cases.api_create_case import cases_create
from eyenet.api.v1.cases.api_get_case import cases_get
from eyenet.api.v1.cases.api_list_cases import cases_list
from eyenet.api.v1.cases.api_list_collaborators import cases_list_collaborators
from eyenet.api.v1.cases.api_list_members import cases_list_members
from eyenet.api.v1.cases.api_remove_member import cases_remove_member
from eyenet.api.v1.cases.api_reopen_case import cases_reopen
from eyenet.api.v1.cases.api_revoke_collaborator import cases_revoke_collaborator
from eyenet.api.v1.cases.api_update_case import cases_update
from eyenet.api.v1.schemas.cases import (
    CaseArchiveRequest,
    CaseCloseRequest,
    CaseCollaboratorAddRequest,
    CaseCollaboratorRevokeRequest,
    CaseCreateRequest,
    CaseMemberAddRequest,
    CaseMemberBulkAddRequest,
    CaseMemberBulkRemoveRequest,
    CaseMemberRemoveRequest,
    CaseMemberSubjectRef,
    CaseReopenRequest,
    CaseUpdateRequest,
)
from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts.enums import CaseRoleOnCase, CaseStatus, CaseSubjectKind
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

pytestmark = pytest.mark.unit

_REASON = "documented for the alpha investigation"
_ARCHIVE_REASON = "archived after the investigation concluded successfully"
_PAGE = CursorParams(offset=0, limit=50, include_total=True)


@pytest.fixture
def audit(storage: BaseRepository) -> AuditEmitter:
    return AuditEmitter(
        BusEnvelopePublisher(MemoryBus()), storage, service="test", instance_id="t0"
    )


async def _make_case(
    storage: BaseRepository,
    audit: AuditEmitter,
    owner: CurrentUser,
    *,
    title: str = "Operation Alpha",
):
    return await cases_create(
        CaseCreateRequest(title=title, description="initial"), owner, storage, audit
    )


# -- create / get / list -----------------------------------------------------


async def test_create_enrolls_creator_as_owner(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    owner = mkuser("write:cases")
    detail = await _make_case(storage, audit, owner)
    assert detail.status is CaseStatus.OPEN
    assert detail.collaborator_count == 1
    collabs = await storage.list_case_collaborators(detail.case_id)
    assert collabs[0].user_id == owner.user_id
    assert collabs[0].role_on_case is CaseRoleOnCase.OWNER


async def test_list_visibility_admin_vs_stranger(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    owner = mkuser("write:cases")
    await _make_case(storage, audit, owner)

    admin = mkuser("read:cases", "admin:case")
    assert len((await cases_list(admin, storage, _PAGE)).items) == 1

    stranger = mkuser("read:cases")
    assert (await cases_list(stranger, storage, _PAGE)).items == []

    # The owner is a collaborator, so they see their own case.
    assert len((await cases_list(owner, storage, _PAGE)).items) == 1


async def test_get_visibility(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    owner = mkuser("write:cases")
    detail = await _make_case(storage, audit, owner)

    got = await cases_get(detail.case_id, owner, storage)
    assert got.case_id == detail.case_id

    admin = mkuser("read:cases", "admin:case")
    assert (await cases_get(detail.case_id, admin, storage)).case_id == detail.case_id

    stranger = mkuser("read:cases")
    with pytest.raises(ResourceNotFound):
        await cases_get(detail.case_id, stranger, storage)


async def test_get_absent_404(storage: BaseRepository, mkuser: Callable[..., CurrentUser]) -> None:
    with pytest.raises(ResourceNotFound):
        await cases_get(uuid4(), mkuser("read:cases", "admin:case"), storage)


# -- update / close / archive / reopen ---------------------------------------


async def test_update_open_then_reject_when_closed(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    owner = mkuser("write:cases")
    detail = await _make_case(storage, audit, owner)

    updated = await cases_update(
        detail.case_id,
        CaseUpdateRequest(title="Operation Beta", reason=_REASON),
        owner,
        storage,
        audit,
    )
    assert updated.title == "Operation Beta"

    await cases_close(detail.case_id, CaseCloseRequest(close_reason=_REASON), owner, storage, audit)
    with pytest.raises(ConflictError):
        await cases_update(
            detail.case_id,
            CaseUpdateRequest(title="Operation Gamma", reason=_REASON),
            owner,
            storage,
            audit,
        )


async def test_close_double_conflict(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    owner = mkuser("write:cases")
    detail = await _make_case(storage, audit, owner)
    closed = await cases_close(
        detail.case_id, CaseCloseRequest(close_reason=_REASON), owner, storage, audit
    )
    assert closed.status is CaseStatus.CLOSED
    with pytest.raises(ConflictError):
        await cases_close(
            detail.case_id, CaseCloseRequest(close_reason=_REASON), owner, storage, audit
        )


async def test_reopen_closed_requires_owner_or_admin(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    owner = mkuser("write:cases")
    detail = await _make_case(storage, audit, owner)
    await cases_close(detail.case_id, CaseCloseRequest(close_reason=_REASON), owner, storage, audit)

    stranger = mkuser("write:cases")  # not a collaborator, no admin:case
    with pytest.raises(ScopeForbidden):
        await cases_reopen(
            detail.case_id, CaseReopenRequest(reopen_reason=_REASON), stranger, storage, audit
        )

    reopened = await cases_reopen(
        detail.case_id, CaseReopenRequest(reopen_reason=_REASON), owner, storage, audit
    )
    assert reopened.status is CaseStatus.OPEN


async def test_reopen_open_conflict(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    owner = mkuser("write:cases")
    detail = await _make_case(storage, audit, owner)
    with pytest.raises(ConflictError):
        await cases_reopen(
            detail.case_id, CaseReopenRequest(reopen_reason=_REASON), owner, storage, audit
        )


async def test_archive_then_reopen_into_successor(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    admin = mkuser("write:cases", "admin:case")
    detail = await _make_case(storage, audit, admin)
    await cases_close(detail.case_id, CaseCloseRequest(close_reason=_REASON), admin, storage, audit)
    archived = await cases_archive(
        detail.case_id, CaseArchiveRequest(archive_reason=_ARCHIVE_REASON), admin, storage, audit
    )
    assert archived.status is CaseStatus.ARCHIVED

    # archived → open mints a successor carrying parent_case_id.
    successor = await cases_reopen(
        detail.case_id, CaseReopenRequest(reopen_reason=_REASON), admin, storage, audit
    )
    assert successor.status is CaseStatus.OPEN
    assert successor.parent_case_id == detail.case_id
    assert successor.case_id != detail.case_id

    # non-admin cannot reopen an archived case.
    plain = mkuser("write:cases")
    with pytest.raises(ScopeForbidden):
        await cases_reopen(
            detail.case_id, CaseReopenRequest(reopen_reason=_REASON), plain, storage, audit
        )


async def test_archive_requires_closed(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    admin = mkuser("write:cases", "admin:case")
    detail = await _make_case(storage, audit, admin)
    with pytest.raises(ConflictError):
        await cases_archive(
            detail.case_id,
            CaseArchiveRequest(archive_reason=_ARCHIVE_REASON),
            admin,
            storage,
            audit,
        )


# -- members -----------------------------------------------------------------


async def test_member_add_list_remove(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    owner = mkuser("write:cases")
    detail = await _make_case(storage, audit, owner)
    subj = uuid4()
    added = await cases_add_member(
        detail.case_id,
        CaseMemberAddRequest(
            subject_kind=CaseSubjectKind.OBSERVATION, subject_id=subj, add_reason=_REASON
        ),
        owner,
        storage,
        audit,
    )
    assert added.active is True

    listed = await cases_list_members(detail.case_id, owner, storage)
    assert [m.member_id for m in listed.items] == [added.member_id]

    # duplicate active member → conflict
    with pytest.raises(ConflictError):
        await cases_add_member(
            detail.case_id,
            CaseMemberAddRequest(
                subject_kind=CaseSubjectKind.OBSERVATION, subject_id=subj, add_reason=_REASON
            ),
            owner,
            storage,
            audit,
        )

    removed = await cases_remove_member(
        detail.case_id,
        added.member_id,
        CaseMemberRemoveRequest(removal_reason=_REASON),
        owner,
        storage,
        audit,
    )
    assert removed.active is False
    assert (await cases_list_members(detail.case_id, owner, storage)).items == []


async def test_member_remove_unknown_404(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    owner = mkuser("write:cases")
    detail = await _make_case(storage, audit, owner)
    with pytest.raises(ResourceNotFound):
        await cases_remove_member(
            detail.case_id,
            uuid4(),
            CaseMemberRemoveRequest(removal_reason=_REASON),
            owner,
            storage,
            audit,
        )


async def test_member_bulk_add_and_remove(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    owner = mkuser("write:cases")
    detail = await _make_case(storage, audit, owner)
    subjects = [
        CaseMemberSubjectRef(subject_kind=CaseSubjectKind.OBSERVATION, subject_id=uuid4())
        for _ in range(3)
    ]
    result = await cases_bulk_add_members(
        detail.case_id,
        CaseMemberBulkAddRequest(subjects=subjects, add_reason=_REASON),
        owner,
        storage,
        audit,
    )
    assert len(result.affected_member_ids) == 3

    removed = await cases_bulk_remove_members(
        detail.case_id,
        CaseMemberBulkRemoveRequest(member_ids=result.affected_member_ids, removal_reason=_REASON),
        owner,
        storage,
        audit,
    )
    assert len(removed.affected_member_ids) == 3
    assert (await cases_list_members(detail.case_id, owner, storage)).items == []


# -- collaborators -----------------------------------------------------------


async def test_collaborator_add_list_revoke(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    admin = mkuser("write:cases", "admin:case")
    detail = await _make_case(storage, audit, admin)
    new_user = uuid4()
    added = await cases_add_collaborator(
        detail.case_id,
        CaseCollaboratorAddRequest(user_id=new_user, role_on_case=CaseRoleOnCase.ANALYST),
        admin,
        storage,
        audit,
    )
    assert added.active is True

    # creator(owner) + the new analyst
    listed = await cases_list_collaborators(detail.case_id, admin, storage)
    assert len(listed.items) == 2

    revoked = await cases_revoke_collaborator(
        detail.case_id,
        added.collaborator_id,
        CaseCollaboratorRevokeRequest(revocation_reason="removed from the investigation"),
        admin,
        storage,
        audit,
    )
    assert revoked.active is False


async def test_collaborator_revoke_unknown_404(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    admin = mkuser("write:cases", "admin:case")
    detail = await _make_case(storage, audit, admin)
    with pytest.raises(ResourceNotFound):
        await cases_revoke_collaborator(
            detail.case_id,
            uuid4(),
            CaseCollaboratorRevokeRequest(revocation_reason="no longer assigned here"),
            admin,
            storage,
            audit,
        )
