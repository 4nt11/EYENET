# SPDX-License-Identifier: AGPL-3.0-or-later
"""M9.B1 acknowledgment nonces — single-use CAS consume (audit.db)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_CONTENT_HASH = "a" * 64
_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_consume_once_returns_true(storage: BaseRepository) -> None:
    nonce = await storage.record_acknowledgment(uuid4(), _CONTENT_HASH, now=_NOW)
    # Within the 60s window.
    assert await storage.consume_acknowledgment(nonce, now=_NOW + timedelta(seconds=10)) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_double_spend_returns_false(storage: BaseRepository) -> None:
    nonce = await storage.record_acknowledgment(uuid4(), _CONTENT_HASH, now=_NOW)
    first = await storage.consume_acknowledgment(nonce, now=_NOW + timedelta(seconds=5))
    second = await storage.consume_acknowledgment(nonce, now=_NOW + timedelta(seconds=6))
    assert first is True
    assert second is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_expired_nonce_returns_false(storage: BaseRepository) -> None:
    nonce = await storage.record_acknowledgment(uuid4(), _CONTENT_HASH, now=_NOW)
    # now strictly past expires_at (issued + 60s).
    assert await storage.consume_acknowledgment(nonce, now=_NOW + timedelta(seconds=61)) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_nonce_returns_false(storage: BaseRepository) -> None:
    assert await storage.consume_acknowledgment(uuid4(), now=_NOW) is False
