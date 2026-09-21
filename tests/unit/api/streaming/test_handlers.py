# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call tests for the five stream handlers (M9.H5).

ASGI-routed handlers are not line-traced by coverage (see the M9 Group F notes),
so the thin authorize-then-respond bodies are exercised by calling them directly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from starlette.responses import StreamingResponse
from uuid_extensions import uuid7

from eyenet.api.deps import AuthError, StreamPrincipal
from eyenet.api.v1.schemas.enums import StreamTopic
from eyenet.api.v1.stream.api_stream_all import stream_all
from eyenet.api.v1.stream.api_stream_audit import stream_audit
from eyenet.api.v1.stream.api_stream_control import stream_control
from eyenet.api.v1.stream.api_stream_linkages import stream_linkages
from eyenet.api.v1.stream.api_stream_personas import stream_personas
from eyenet.bus.memory import MemoryBus
from eyenet.contracts.enums import SystemUserRole
from eyenet.storage.factory import get_repository

from .conftest import FakeRequest

pytestmark = pytest.mark.unit


def _principal(topics: set[str]) -> StreamPrincipal:
    return StreamPrincipal(
        user_id=UUID(str(uuid7())),
        username="op",
        role=SystemUserRole.ADMIN,
        topics=frozenset(topics),
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
    )


@pytest.mark.parametrize(
    ("handler", "topic"),
    [
        (stream_linkages, StreamTopic.ATTRIBUTION_LINKAGE),
        (stream_personas, StreamTopic.ATTRIBUTION_PERSONA),
        (stream_audit, StreamTopic.EYENET_AUDIT),
        (stream_control, StreamTopic.EYENET_CONTROL),
    ],
)
async def test_single_topic_handler_authorizes_and_streams(handler, topic) -> None:
    p = _principal({topic.value})
    resp = await handler(
        request=FakeRequest(),  # type: ignore[arg-type]
        principal=p,
        bus=MemoryBus(),
        storage=get_repository(in_memory=True),
        token=None,
        last_event_id=None,
    )
    assert isinstance(resp, StreamingResponse)
    assert resp.media_type == "text/event-stream"


@pytest.mark.parametrize(
    ("handler", "topic"),
    [
        (stream_linkages, StreamTopic.ATTRIBUTION_LINKAGE),
        (stream_audit, StreamTopic.EYENET_AUDIT),
    ],
)
async def test_single_topic_handler_rejects_missing_topic(handler, topic) -> None:
    p = _principal({"eyenet.control"})  # not the endpoint's topic
    with pytest.raises(AuthError):
        await handler(
            request=FakeRequest(),  # type: ignore[arg-type]
            principal=p,
            bus=MemoryBus(),
            storage=get_repository(in_memory=True),
            token=None,
            last_event_id=None,
        )


async def test_all_handler_requires_exact_topic_set() -> None:
    p = _principal({"attribution.linkage", "eyenet.audit"})
    resp = await stream_all(
        request=FakeRequest(),  # type: ignore[arg-type]
        principal=p,
        bus=MemoryBus(),
        storage=get_repository(in_memory=True),
        topic=[StreamTopic.ATTRIBUTION_LINKAGE, StreamTopic.EYENET_AUDIT],
        token=None,
        last_event_id=None,
    )
    assert isinstance(resp, StreamingResponse)


async def test_all_handler_rejects_topic_drift() -> None:
    p = _principal({"attribution.linkage", "eyenet.audit"})
    with pytest.raises(AuthError):
        await stream_all(
            request=FakeRequest(),  # type: ignore[arg-type]
            principal=p,
            bus=MemoryBus(),
            storage=get_repository(in_memory=True),
            topic=[StreamTopic.ATTRIBUTION_LINKAGE],  # missing eyenet.audit
            token=None,
            last_event_id=None,
        )
