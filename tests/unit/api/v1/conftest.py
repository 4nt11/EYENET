# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixtures for direct-call handler unit tests (M9.F1-F4).

These call the read handlers as plain coroutines with an in-memory repository
and a constructed CurrentUser, bypassing the ASGI routing layer (which the
integration tests exercise but coverage cannot trace). This is where the
handler-body + read-method coverage is credited.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser
from eyenet.contracts.enums import SystemUserRole
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def mkuser() -> Callable[..., CurrentUser]:
    def _make(*scopes: str) -> CurrentUser:
        return CurrentUser(
            user_id=uuid4(),
            username="op",
            role=SystemUserRole.ADMIN,
            effective_scopes=frozenset(scopes),
            token_expires_at=None,
        )

    return _make
