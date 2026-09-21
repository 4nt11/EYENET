# SPDX-License-Identifier: AGPL-3.0-or-later
"""BaseRepository.ping() — cheap liveness read backing /v1/readyz."""

from __future__ import annotations

import pytest

from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


async def test_ping_returns_none_on_open_backend() -> None:
    storage: BaseRepository = get_repository(in_memory=True)
    assert await storage.ping() is None
