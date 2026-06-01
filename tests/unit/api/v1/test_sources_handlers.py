# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the D1 Sources handlers (M9.D1).

Calls handlers as plain coroutines with an in-memory repo + constructed
CurrentUser, bypassing ASGI routing (which coverage can't trace). Scope
enforcement (RequireScope → 403) is an ASGI concern, exercised in the
slice-4 smoke test, not here.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser, ResourceNotFound
from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.schemas.sources import (
    AddSourceDomainRequest,
    BridgeSummary,
    CreateSourceRequest,
    SourceDetail,
    UpdateSourceDomainRequest,
    UpdateSourceRequest,
)
from eyenet.api.v1.sources.api_add_source_domain import sources_add_domain
from eyenet.api.v1.sources.api_create_source import sources_create
from eyenet.api.v1.sources.api_get_bridge_summary import sources_bridge_summary
from eyenet.api.v1.sources.api_get_source import sources_get
from eyenet.api.v1.sources.api_list_source_domains import sources_list_domains
from eyenet.api.v1.sources.api_list_sources import sources_list
from eyenet.api.v1.sources.api_remove_source_domain import sources_remove_domain
from eyenet.api.v1.sources.api_update_source import sources_update
from eyenet.api.v1.sources.api_update_source_domain import sources_update_domain
from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts.enums import SourceDomainPatternKind, SourceKind
from eyenet.storage.errors import SourceCanonicalUrlError, SourceDomainOverlapError
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

pytestmark = pytest.mark.unit


@pytest.fixture
def audit(storage: BaseRepository) -> AuditEmitter:
    return AuditEmitter(
        BusEnvelopePublisher(MemoryBus()),
        storage,
        service="test",
        instance_id="t0",
    )


def _page(limit: int = 50, *, include_total: bool = False) -> CursorParams:
    return CursorParams(offset=0, limit=limit, include_total=include_total)


# --- create + get + list --------------------------------------------------


async def test_create_and_get_source(
    storage: BaseRepository,
    audit: AuditEmitter,
    mkuser: Callable[..., CurrentUser],
) -> None:
    user = mkuser("write:sources")
    detail = await sources_create(
        CreateSourceRequest(kind=SourceKind.TELEGRAM, display_name="tg:alpha", notes="seed"),
        user,
        storage,
        audit,
    )
    assert isinstance(detail, SourceDetail)
    assert detail.display_name == "tg:alpha"
    assert detail.active_domain_count == 0

    fetched = await sources_get(detail.source_id, mkuser("read:sources"), storage)
    assert fetched.source_id == detail.source_id
    assert fetched.notes == "seed"


async def test_get_unknown_source_404(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    with pytest.raises(ResourceNotFound):
        await sources_get(uuid4(), mkuser("read:sources"), storage)


async def test_list_sources_paginates(
    storage: BaseRepository,
    audit: AuditEmitter,
    mkuser: Callable[..., CurrentUser],
) -> None:
    user = mkuser("write:sources")
    for i in range(3):
        await sources_create(
            CreateSourceRequest(kind=SourceKind.TELEGRAM, display_name=f"tg:{i}"),
            user,
            storage,
            audit,
        )
    page = await sources_list(mkuser("read:sources"), storage, _page(limit=2, include_total=True))
    assert len(page.items) == 2
    assert page.next_cursor is not None
    assert page.estimated_total == 3


# --- update ---------------------------------------------------------------


async def test_update_source_fields(
    storage: BaseRepository,
    audit: AuditEmitter,
    mkuser: Callable[..., CurrentUser],
) -> None:
    user = mkuser("write:sources")
    created = await sources_create(
        CreateSourceRequest(kind=SourceKind.TELEGRAM, display_name="tg:x"), user, storage, audit
    )
    updated = await sources_update(
        created.source_id,
        UpdateSourceRequest(display_name="tg:renamed", notes="now annotated"),
        user,
        storage,
        audit,
    )
    assert updated.display_name == "tg:renamed"
    assert updated.notes == "now annotated"


async def test_update_unknown_source_404(
    storage: BaseRepository,
    audit: AuditEmitter,
    mkuser: Callable[..., CurrentUser],
) -> None:
    with pytest.raises(ResourceNotFound):
        await sources_update(
            uuid4(), UpdateSourceRequest(notes="x"), mkuser("write:sources"), storage, audit
        )


async def test_update_canonical_url_without_primary_rejected(
    storage: BaseRepository,
    audit: AuditEmitter,
    mkuser: Callable[..., CurrentUser],
) -> None:
    user = mkuser("write:sources")
    created = await sources_create(
        CreateSourceRequest(kind=SourceKind.TELEGRAM, display_name="tg:nc"), user, storage, audit
    )
    with pytest.raises(SourceCanonicalUrlError):
        await sources_update(
            created.source_id,
            UpdateSourceRequest(canonical_url="https://no-primary.example"),
            user,
            storage,
            audit,
        )


async def test_update_canonical_url_happy(
    storage: BaseRepository,
    audit: AuditEmitter,
    mkuser: Callable[..., CurrentUser],
) -> None:
    user = mkuser("write:sources")
    created = await sources_create(
        CreateSourceRequest(kind=SourceKind.TELEGRAM, display_name="tg:c"), user, storage, audit
    )
    await sources_add_domain(
        created.source_id,
        AddSourceDomainRequest(
            pattern="canon.example",
            pattern_kind=SourceDomainPatternKind.EXACT,
            is_primary=True,
        ),
        user,
        storage,
        audit,
    )
    updated = await sources_update(
        created.source_id,
        UpdateSourceRequest(canonical_url="https://canon.example/info"),
        user,
        storage,
        audit,
    )
    assert updated.canonical_url == "https://canon.example/info"


# --- domains: add / list / overlap / swap / remove ------------------------


async def test_add_and_list_domains(
    storage: BaseRepository,
    audit: AuditEmitter,
    mkuser: Callable[..., CurrentUser],
) -> None:
    user = mkuser("write:sources")
    src = await sources_create(
        CreateSourceRequest(kind=SourceKind.TELEGRAM, display_name="tg:d"), user, storage, audit
    )
    view = await sources_add_domain(
        src.source_id,
        AddSourceDomainRequest(
            pattern="a.example", pattern_kind=SourceDomainPatternKind.EXACT, is_primary=True
        ),
        user,
        storage,
        audit,
    )
    assert view.pattern == "a.example"
    assert view.is_primary is True

    domains = await sources_list_domains(src.source_id, mkuser("read:sources"), storage)
    assert {d.pattern for d in domains} == {"a.example"}


async def test_add_domain_overlap_raises(
    storage: BaseRepository,
    audit: AuditEmitter,
    mkuser: Callable[..., CurrentUser],
) -> None:
    user = mkuser("write:sources")
    src = await sources_create(
        CreateSourceRequest(kind=SourceKind.TELEGRAM, display_name="tg:o"), user, storage, audit
    )
    await sources_add_domain(
        src.source_id,
        AddSourceDomainRequest(pattern="dup.example", pattern_kind=SourceDomainPatternKind.EXACT),
        user,
        storage,
        audit,
    )
    # Same pattern again → in-transaction overlap. Propagates to the app's
    # 409 handler at the ASGI layer.
    with pytest.raises(SourceDomainOverlapError):
        await sources_add_domain(
            src.source_id,
            AddSourceDomainRequest(
                pattern="dup.example", pattern_kind=SourceDomainPatternKind.EXACT
            ),
            user,
            storage,
            audit,
        )


async def test_add_domain_unknown_source_404(
    storage: BaseRepository,
    audit: AuditEmitter,
    mkuser: Callable[..., CurrentUser],
) -> None:
    with pytest.raises(ResourceNotFound):
        await sources_add_domain(
            uuid4(),
            AddSourceDomainRequest(pattern="x.example", pattern_kind=SourceDomainPatternKind.EXACT),
            mkuser("write:sources"),
            storage,
            audit,
        )


async def test_swap_primary_domain(
    storage: BaseRepository,
    audit: AuditEmitter,
    mkuser: Callable[..., CurrentUser],
) -> None:
    user = mkuser("write:sources")
    src = await sources_create(
        CreateSourceRequest(kind=SourceKind.TELEGRAM, display_name="tg:sw"), user, storage, audit
    )
    await sources_add_domain(
        src.source_id,
        AddSourceDomainRequest(
            pattern="first.example", pattern_kind=SourceDomainPatternKind.EXACT, is_primary=True
        ),
        user,
        storage,
        audit,
    )
    second = await sources_add_domain(
        src.source_id,
        AddSourceDomainRequest(
            pattern="second.example", pattern_kind=SourceDomainPatternKind.EXACT
        ),
        user,
        storage,
        audit,
    )
    swapped = await sources_update_domain(
        src.source_id,
        second.domain_id,
        UpdateSourceDomainRequest(is_primary=True),
        user,
        storage,
        audit,
    )
    assert swapped.is_primary is True


async def test_update_domain_unknown_404(
    storage: BaseRepository,
    audit: AuditEmitter,
    mkuser: Callable[..., CurrentUser],
) -> None:
    user = mkuser("write:sources")
    src = await sources_create(
        CreateSourceRequest(kind=SourceKind.TELEGRAM, display_name="tg:u"), user, storage, audit
    )
    with pytest.raises(ResourceNotFound):
        await sources_update_domain(
            src.source_id,
            uuid4(),
            UpdateSourceDomainRequest(is_primary=True),
            user,
            storage,
            audit,
        )


async def test_remove_domain_soft_deletes(
    storage: BaseRepository,
    audit: AuditEmitter,
    mkuser: Callable[..., CurrentUser],
) -> None:
    user = mkuser("write:sources")
    src = await sources_create(
        CreateSourceRequest(kind=SourceKind.TELEGRAM, display_name="tg:rm"), user, storage, audit
    )
    dom = await sources_add_domain(
        src.source_id,
        AddSourceDomainRequest(pattern="gone.example", pattern_kind=SourceDomainPatternKind.EXACT),
        user,
        storage,
        audit,
    )
    resp = await sources_remove_domain(src.source_id, dom.domain_id, user, storage, audit)
    assert resp.status_code == 204
    # Active list excludes it; include_removed surfaces it.
    active = await sources_list_domains(src.source_id, mkuser("read:sources"), storage)
    assert active == []
    with_removed = await sources_list_domains(
        src.source_id, mkuser("read:sources"), storage, include_removed=True
    )
    assert len(with_removed) == 1


async def test_remove_domain_unknown_404(
    storage: BaseRepository,
    audit: AuditEmitter,
    mkuser: Callable[..., CurrentUser],
) -> None:
    user = mkuser("write:sources")
    src = await sources_create(
        CreateSourceRequest(kind=SourceKind.TELEGRAM, display_name="tg:rmx"), user, storage, audit
    )
    with pytest.raises(ResourceNotFound):
        await sources_remove_domain(src.source_id, uuid4(), user, storage, audit)


# --- bridge summary -------------------------------------------------------


async def test_bridge_summary_empty(
    storage: BaseRepository,
    audit: AuditEmitter,
    mkuser: Callable[..., CurrentUser],
) -> None:
    user = mkuser("write:sources")
    src = await sources_create(
        CreateSourceRequest(kind=SourceKind.TELEGRAM, display_name="tg:bs"), user, storage, audit
    )
    summary = await sources_bridge_summary(src.source_id, mkuser("read:sources"), storage)
    assert isinstance(summary, BridgeSummary)
    assert summary.source_id == src.source_id
    assert summary.resolved == 0


async def test_bridge_summary_unknown_404(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    with pytest.raises(ResourceNotFound):
        await sources_bridge_summary(uuid4(), mkuser("read:sources"), storage)
