# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit test for PUT /v1/actors/{id}/assessment (actors_set_assessment)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser, ResourceNotFound
from eyenet.api.v1.actors.api_get_actor import actors_get
from eyenet.api.v1.actors.api_set_assessment import actors_set_assessment
from eyenet.api.v1.schemas.actors import SetActorAssessmentRequest
from eyenet.contracts.enums import SourceKind
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


async def _seed_actor(storage: BaseRepository):
    source_id = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=_NOW
    )
    return await storage.upsert_actor(
        source_id=source_id, actor_key="a:1", platform_userid="1",
        handle="h", display_name=None, seen_at=_NOW,
    )


async def test_set_assessment_persists_and_surfaces(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    actor_id = await _seed_actor(storage)
    body = SetActorAssessmentRequest(assessment="high-confidence loader operator", reason="triage")
    res = await actors_set_assessment(actor_id, body, mkuser("write:actors"), storage, _audit(storage))
    assert res.assessment == "high-confidence loader operator"
    # Durable on return: the actor detail now carries it.
    detail = await actors_get(actor_id, mkuser("read:actors"), storage)
    assert detail.assessment == "high-confidence loader operator"


async def test_set_assessment_unknown_actor_raises(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    body = SetActorAssessmentRequest(assessment="x", reason="y")
    with pytest.raises(ResourceNotFound):
        await actors_set_assessment(uuid4(), body, mkuser("write:actors"), storage, _audit(storage))


def _audit(storage: BaseRepository):
    from eyenet.bus.memory import MemoryBus
    from eyenet.bus.publisher import BusEnvelopePublisher
    from eyenet.telemetry.audit import AuditEmitter

    return AuditEmitter(
        BusEnvelopePublisher(MemoryBus()), storage, service="test", instance_id="t0"
    )
