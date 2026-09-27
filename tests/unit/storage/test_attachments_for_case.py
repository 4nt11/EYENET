# SPDX-License-Identifier: AGPL-3.0-or-later
"""list_attachments_for_case / count_attachments_for_case (AttachmentsMixin).

Direct-membership semantics (§4.10.1): only attachments added to the case via
``case_member`` (subject_kind=attachment, not removed) are returned. Mirrors
tests/unit/storage/test_observations_for_case.py. Types against BaseRepository
+ get_repository per Rule 2.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from eyenet.contracts.enums import AttachmentKind, CaseSubjectKind, SensitivityTier
from eyenet.contracts.message import AttachmentRow
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_USER = UUID("00000000-0000-0000-0000-0000000000ff")
_CTX = {"service": "test", "instance_id": "t0"}


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _hex64() -> str:
    return uuid4().hex + uuid4().hex


async def _put(storage: BaseRepository) -> UUID:
    return await storage.put_attachment(
        AttachmentRow(
            message_id=uuid4(),
            kind=AttachmentKind.DOCUMENT,
            mime="application/octet-stream",
            size_bytes=11,
            sha256=_hex64(),
            storage_uri="blob/x.bin",
            classifier_tier=SensitivityTier.NORMAL,
        )
    )


async def _new_case(storage: BaseRepository) -> UUID:
    case = await storage.create_case(
        title="evidence case", description=None, opened_by_user_id=_USER, **_CTX
    )
    return case.id


async def _add_member(storage: BaseRepository, case_id: UUID, blob_id: UUID) -> UUID:
    member = await storage.add_case_member(
        case_id=case_id,
        subject_kind=CaseSubjectKind.ATTACHMENT,
        subject_id=blob_id,
        added_by_user_id=_USER,
        reason="seed evidence member",
        **_CTX,
    )
    return member.id


async def test_empty_case_has_no_attachments(storage: BaseRepository) -> None:
    case_id = await _new_case(storage)
    assert await storage.list_attachments_for_case(case_id, limit=10) == []
    assert await storage.count_attachments_for_case(case_id) == 0


async def test_only_direct_members_returned(storage: BaseRepository) -> None:
    case_id = await _new_case(storage)
    member = await _put(storage)
    await _put(storage)  # non-member
    await _add_member(storage, case_id, member)

    rows = await storage.list_attachments_for_case(case_id, limit=10)
    assert [r.id for r in rows] == [member]
    assert await storage.count_attachments_for_case(case_id) == 1


async def test_newest_first(storage: BaseRepository) -> None:
    # id is uuid7 = time-ordered; the second insert sorts first under id DESC.
    case_id = await _new_case(storage)
    older = await _put(storage)
    newer = await _put(storage)
    for blob_id in (older, newer):
        await _add_member(storage, case_id, blob_id)
    rows = await storage.list_attachments_for_case(case_id, limit=10)
    assert [r.id for r in rows] == [newer, older]


async def test_removed_member_excluded(storage: BaseRepository) -> None:
    case_id = await _new_case(storage)
    blob_id = await _put(storage)
    member_id = await _add_member(storage, case_id, blob_id)

    await storage.remove_case_member(
        member_id=member_id, remover_user_id=_USER, reason="no longer evidence", **_CTX
    )
    assert await storage.list_attachments_for_case(case_id, limit=10) == []
    assert await storage.count_attachments_for_case(case_id) == 0


async def test_scoped_to_case(storage: BaseRepository) -> None:
    case_a = await _new_case(storage)
    case_b = await _new_case(storage)
    blob_id = await _put(storage)
    await _add_member(storage, case_a, blob_id)
    assert await storage.count_attachments_for_case(case_a) == 1
    assert await storage.count_attachments_for_case(case_b) == 0
