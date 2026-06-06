# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the D4 seed-roots handlers (Slice C, §4.12).

Covers the GET/PUT/POST handlers plus the substantive DoD: changing a case's
seed roots shifts the §4.12.3 candidate→case resolution that the eligibility
predicate reads.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.api.deps import ConflictError, CurrentUser, ResourceNotFound
from eyenet.api.v1.cases.api_archive_case import cases_archive
from eyenet.api.v1.cases.api_close_case import cases_close
from eyenet.api.v1.cases.api_create_case import cases_create
from eyenet.api.v1.cases.api_get_seed_roots import cases_get_seed_roots
from eyenet.api.v1.cases.api_promote_seed_root import cases_promote_seed_root
from eyenet.api.v1.cases.api_replace_seed_roots import cases_replace_seed_roots
from eyenet.api.v1.schemas.cases import (
    CaseArchiveRequest,
    CaseCloseRequest,
    CaseCreateRequest,
    CaseSeedRootsReplaceRequest,
)
from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts.enums import MentionKind, SourceKind
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 5, tzinfo=UTC)
_REASON = "documented for the alpha investigation"
_ARCHIVE_REASON = "archived after the investigation concluded successfully"


@pytest.fixture
def audit(storage: BaseRepository) -> AuditEmitter:
    return AuditEmitter(
        BusEnvelopePublisher(MemoryBus()), storage, service="test", instance_id="t0"
    )


async def _make_case(storage: BaseRepository, audit: AuditEmitter, owner: CurrentUser):
    return await cases_create(
        CaseCreateRequest(title="Operation Alpha", description=None), owner, storage, audit
    )


async def test_get_default_empty(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    owner = mkuser("write:cases", "read:cases")
    detail = await _make_case(storage, audit, owner)
    roots = await cases_get_seed_roots(detail.case_id, owner, storage)
    assert roots.case_id == detail.case_id
    assert roots.seed_root_group_ids == []


async def test_put_then_get_round_trip(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    owner = mkuser("write:cases", "read:cases")
    detail = await _make_case(storage, audit, owner)
    g1, g2 = uuid4(), uuid4()
    put = await cases_replace_seed_roots(
        detail.case_id,
        CaseSeedRootsReplaceRequest(seed_root_group_ids=[g1, g2]),
        owner,
        storage,
        audit,
    )
    assert set(put.seed_root_group_ids) == {g1, g2}
    got = await cases_get_seed_roots(detail.case_id, owner, storage)
    assert set(got.seed_root_group_ids) == {g1, g2}


async def test_promote_is_idempotent(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    owner = mkuser("write:cases", "read:cases", "admin:case")
    detail = await _make_case(storage, audit, owner)
    g = uuid4()
    first = await cases_promote_seed_root(detail.case_id, g, owner, storage, audit)
    assert first.seed_root_group_ids == [g]
    second = await cases_promote_seed_root(detail.case_id, g, owner, storage, audit)
    assert second.seed_root_group_ids == [g]


async def test_put_on_archived_conflict(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    admin = mkuser("write:cases", "read:cases", "admin:case")
    detail = await _make_case(storage, audit, admin)
    await cases_close(detail.case_id, CaseCloseRequest(close_reason=_REASON), admin, storage, audit)
    await cases_archive(
        detail.case_id, CaseArchiveRequest(archive_reason=_ARCHIVE_REASON), admin, storage, audit
    )
    with pytest.raises(ConflictError):
        await cases_replace_seed_roots(
            detail.case_id,
            CaseSeedRootsReplaceRequest(seed_root_group_ids=[uuid4()]),
            admin,
            storage,
            audit,
        )


async def test_absent_case_404(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser("write:cases", "read:cases", "admin:case")
    with pytest.raises(ResourceNotFound):
        await cases_get_seed_roots(uuid4(), user, storage)
    with pytest.raises(ResourceNotFound):
        await cases_replace_seed_roots(
            uuid4(), CaseSeedRootsReplaceRequest(seed_root_group_ids=[]), user, storage, audit
        )
    with pytest.raises(ResourceNotFound):
        await cases_promote_seed_root(uuid4(), uuid4(), user, storage, audit)


async def test_seed_root_change_shifts_candidate_resolution(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    """The D4 payoff: editing seed roots moves the §4.12.3 candidate→case
    resolution the eligibility predicate depends on."""
    owner = mkuser("write:cases", "read:cases")
    source_id = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:d4", created_at=_NOW
    )
    seed_group = uuid4()
    candidate, _ = await storage.record_candidate_mention(
        source_id=source_id,
        platform_groupid="@target",
        observed_by_collector_id=uuid4(),
        observed_in_group_id=uuid4(),
        seed_root_id=seed_group,
        depth_from_root=1,
        mention_evidence_ref="ev:d4:1",
        mention_kind=MentionKind.USERNAME_MENTION,
        mentioned_at_source=_NOW,
        mentioned_at_ingest=_NOW,
        mentioning_actor_id=uuid4(),
    )
    detail = await _make_case(storage, audit, owner)

    # Before: the case claims no seed roots, so it does not resolve the candidate.
    assert await storage.resolve_case_for_candidate(candidate.id) is None

    # PUT the candidate's seed-root group onto the case.
    await cases_replace_seed_roots(
        detail.case_id,
        CaseSeedRootsReplaceRequest(seed_root_group_ids=[seed_group]),
        owner,
        storage,
        audit,
    )

    # After: the candidate now resolves to this case.
    resolved = await storage.resolve_case_for_candidate(candidate.id)
    assert resolved is not None
    assert resolved.id == detail.case_id
