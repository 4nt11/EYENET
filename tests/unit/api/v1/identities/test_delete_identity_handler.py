# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for DELETE /v1/identities/{id} (ASGI-untraceable).

Delete removes an unused/mistaken identity; a collector-bound or IN_USE one is
refused with 409 (burn is the retire-in-place path for a compromised identity).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException

from eyenet.api.deps import CurrentUser, ResourceNotFound
from eyenet.api.v1.identities.api_delete_identity import identities_delete
from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts.enums import IdentityState, SourceKind
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

pytestmark = pytest.mark.unit


@pytest.fixture
def audit(storage: BaseRepository) -> AuditEmitter:
    return AuditEmitter(BusEnvelopePublisher(MemoryBus()), storage, service="t", instance_id="t0")


async def _source(storage: BaseRepository) -> object:
    return await storage.upsert_source(
        kind=SourceKind.FORUM, display_name="fm", created_at=datetime.now(tz=UTC)
    )


async def test_delete_unused_identity(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    sid = await _source(storage)
    ident = await storage.create_identity(name="id1", source_id=sid, session_path="")
    await identities_delete(
        current_user=mkuser("write:identity"),
        storage=storage,
        audit=audit,
        identity_id=str(ident.id),
    )
    assert await storage.get_identity(ident.id) is None


async def test_delete_identity_bound_is_409(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    sid = await _source(storage)
    ident = await storage.create_identity(name="id2", source_id=sid, session_path="")
    await storage.create_collector(
        instance_name="forum-collector-1",
        kind=SourceKind.FORUM,
        source_id=sid,
        identity_id=ident.id,
        config={},
        created_at=datetime.now(tz=UTC),
        created_by_user_id=uuid4(),
    )
    with pytest.raises(HTTPException) as ei:
        await identities_delete(
            current_user=mkuser("write:identity"),
            storage=storage,
            audit=audit,
            identity_id=str(ident.id),
        )
    assert ei.value.status_code == 409
    assert ei.value.detail["references"]["collector"] == 1  # type: ignore[index]


async def test_delete_identity_in_use_is_409(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    sid = await _source(storage)
    ident = await storage.create_identity(
        name="id3", source_id=sid, session_path="", state=IdentityState.IN_USE
    )
    with pytest.raises(HTTPException) as ei:
        await identities_delete(
            current_user=mkuser("write:identity"),
            storage=storage,
            audit=audit,
            identity_id=str(ident.id),
        )
    assert ei.value.status_code == 409


async def test_delete_identity_bad_id_404(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    with pytest.raises(ResourceNotFound):
        await identities_delete(
            current_user=mkuser("write:identity"),
            storage=storage,
            audit=audit,
            identity_id="not-a-uuid",
        )
