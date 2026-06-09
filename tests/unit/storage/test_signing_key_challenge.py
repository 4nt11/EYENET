# SPDX-License-Identifier: AGPL-3.0-or-later
"""PHASE-4 signing-key registration challenge — user-bound single-use CAS (audit.db)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mint_then_consume_once_returns_true(storage: BaseRepository) -> None:
    user_id = uuid4()
    nonce = await storage.mint_signing_key_challenge(user_id, now=_NOW)
    # Within the 60s window, by the same user.
    consumed = await storage.consume_signing_key_challenge(
        nonce, user_id, now=_NOW + timedelta(seconds=10)
    )
    assert consumed is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replay_second_consume_returns_false(storage: BaseRepository) -> None:
    user_id = uuid4()
    nonce = await storage.mint_signing_key_challenge(user_id, now=_NOW)
    first = await storage.consume_signing_key_challenge(
        nonce, user_id, now=_NOW + timedelta(seconds=5)
    )
    second = await storage.consume_signing_key_challenge(
        nonce, user_id, now=_NOW + timedelta(seconds=6)
    )
    assert first is True
    assert second is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nonce_for_user_a_cannot_be_consumed_by_user_b(storage: BaseRepository) -> None:
    """USER-BINDING — the security-critical predicate.

    A nonce minted for user A is invisible to user B's consume, even though
    the nonce value is identical and unexpired.
    """
    user_a = uuid4()
    user_b = uuid4()
    nonce = await storage.mint_signing_key_challenge(user_a, now=_NOW)
    # User B presents A's nonce → rejected (no rows matched).
    assert await storage.consume_signing_key_challenge(nonce, user_b, now=_NOW) is False
    # And A can STILL consume it — B's attempt did not burn it.
    assert await storage.consume_signing_key_challenge(nonce, user_a, now=_NOW) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_expired_nonce_returns_false(storage: BaseRepository) -> None:
    user_id = uuid4()
    nonce = await storage.mint_signing_key_challenge(user_id, now=_NOW)
    # now strictly past expires_at (minted + 60s).
    assert (
        await storage.consume_signing_key_challenge(
            nonce, user_id, now=_NOW + timedelta(seconds=61)
        )
        is False
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_nonce_returns_false(storage: BaseRepository) -> None:
    assert await storage.consume_signing_key_challenge(uuid4(), uuid4(), now=_NOW) is False
