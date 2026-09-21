# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixtures for the SSE streaming unit tests (M9 Group H).

Direct-call harness: the generator and replay source are exercised without the
ASGI stack (coverage cannot trace ASGI-routed handlers — see the M9 Group F
notes), driving events through a real ``MemoryBus`` and an in-memory repository.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from eyenet.api.deps import StreamPrincipal
from eyenet.bus.memory import MemoryBus
from eyenet.contracts.enums import SystemUserRole
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

ALL_TOPICS = frozenset(
    {"attribution.linkage", "attribution.persona", "eyenet.audit", "eyenet.control"}
)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.fixture
def bus() -> MemoryBus:
    return MemoryBus()


@pytest.fixture
def principal() -> StreamPrincipal:
    return StreamPrincipal(
        user_id=uuid4(),
        username="op",
        role=SystemUserRole.ADMIN,
        topics=ALL_TOPICS,
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
    )


class FakeRequest:
    """Minimal ``Request`` stand-in — only ``is_disconnected`` is consulted."""

    def __init__(self) -> None:
        self._disconnected = False

    def disconnect(self) -> None:
        self._disconnected = True

    async def is_disconnected(self) -> bool:
        return self._disconnected


@pytest.fixture
def fake_request() -> FakeRequest:
    return FakeRequest()
