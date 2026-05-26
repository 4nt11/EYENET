"""Storage tests for M9.A3 ``mfa_challenge`` table (BaseRepository).

Covers create / get / consume / bump / count / clear through the abstract
repo per CLAUDE.md §2.3 Rule 2 (no direct backend import).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from eyenet.contracts.mfa import MfaChallengeRow
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)
_EXP = _NOW + timedelta(seconds=90)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.mark.unit
async def test_create_and_get_round_trip(storage: BaseRepository) -> None:
    user_id = uuid4()
    row = await storage.create_mfa_challenge(
        user_id=user_id,
        issued_at=_NOW,
        expires_at=_EXP,
    )
    assert isinstance(row, MfaChallengeRow)
    assert row.user_id == user_id
    assert row.consumed_at is None
    assert row.failed_attempts == 0

    fetched = await storage.get_mfa_challenge(row.challenge_id)
    assert fetched is not None
    assert fetched.challenge_id == row.challenge_id


@pytest.mark.unit
async def test_get_unknown_returns_none(storage: BaseRepository) -> None:
    assert await storage.get_mfa_challenge(uuid4()) is None


@pytest.mark.unit
async def test_consume_marks_consumed_at(storage: BaseRepository) -> None:
    user_id = uuid4()
    row = await storage.create_mfa_challenge(
        user_id=user_id,
        issued_at=_NOW,
        expires_at=_EXP,
    )
    consumed = await storage.consume_mfa_challenge(
        challenge_id=row.challenge_id,
        consumed_at=_NOW + timedelta(seconds=5),
    )
    assert consumed.consumed_at == _NOW + timedelta(seconds=5)


@pytest.mark.unit
async def test_double_consume_raises(storage: BaseRepository) -> None:
    row = await storage.create_mfa_challenge(
        user_id=uuid4(),
        issued_at=_NOW,
        expires_at=_EXP,
    )
    await storage.consume_mfa_challenge(
        challenge_id=row.challenge_id,
        consumed_at=_NOW + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="already consumed"):
        await storage.consume_mfa_challenge(
            challenge_id=row.challenge_id,
            consumed_at=_NOW + timedelta(seconds=2),
        )


@pytest.mark.unit
async def test_consume_unknown_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.consume_mfa_challenge(
            challenge_id=uuid4(),
            consumed_at=_NOW,
        )


@pytest.mark.unit
async def test_bump_failures_increments(storage: BaseRepository) -> None:
    row = await storage.create_mfa_challenge(
        user_id=uuid4(),
        issued_at=_NOW,
        expires_at=_EXP,
    )
    assert await storage.bump_mfa_challenge_failures(row.challenge_id) == 1
    assert await storage.bump_mfa_challenge_failures(row.challenge_id) == 2
    refetched = await storage.get_mfa_challenge(row.challenge_id)
    assert refetched is not None
    assert refetched.failed_attempts == 2


@pytest.mark.unit
async def test_bump_unknown_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.bump_mfa_challenge_failures(uuid4())


@pytest.mark.unit
async def test_count_recent_failures_window(storage: BaseRepository) -> None:
    user_id = uuid4()
    other_user = uuid4()

    # 3 failed challenges in window for user_id
    for _ in range(3):
        row = await storage.create_mfa_challenge(
            user_id=user_id,
            issued_at=_NOW,
            expires_at=_EXP,
        )
        await storage.bump_mfa_challenge_failures(row.challenge_id)

    # 1 not-failed challenge — should NOT count
    await storage.create_mfa_challenge(
        user_id=user_id,
        issued_at=_NOW,
        expires_at=_EXP,
    )

    # 1 failed challenge for other user — should NOT count
    other_row = await storage.create_mfa_challenge(
        user_id=other_user,
        issued_at=_NOW,
        expires_at=_EXP,
    )
    await storage.bump_mfa_challenge_failures(other_row.challenge_id)

    # 1 failed challenge BEFORE window — should NOT count
    old_row = await storage.create_mfa_challenge(
        user_id=user_id,
        issued_at=_NOW - timedelta(hours=1),
        expires_at=_NOW - timedelta(hours=1) + timedelta(seconds=90),
    )
    await storage.bump_mfa_challenge_failures(old_row.challenge_id)

    assert (
        await storage.count_recent_mfa_failures(
            user_id=user_id,
            since=_NOW - timedelta(minutes=15),
        )
        == 3
    )


@pytest.mark.unit
async def test_clear_failures_zeroes_in_window(storage: BaseRepository) -> None:
    user_id = uuid4()
    in_window = []
    for _ in range(3):
        row = await storage.create_mfa_challenge(
            user_id=user_id,
            issued_at=_NOW,
            expires_at=_EXP,
        )
        await storage.bump_mfa_challenge_failures(row.challenge_id)
        in_window.append(row.challenge_id)

    out_of_window = await storage.create_mfa_challenge(
        user_id=user_id,
        issued_at=_NOW - timedelta(hours=1),
        expires_at=_NOW - timedelta(hours=1) + timedelta(seconds=90),
    )
    await storage.bump_mfa_challenge_failures(out_of_window.challenge_id)

    cleared = await storage.clear_mfa_failures(
        user_id=user_id,
        since=_NOW - timedelta(minutes=15),
    )
    assert cleared == 3

    for cid in in_window:
        row = await storage.get_mfa_challenge(cid)
        assert row is not None
        assert row.failed_attempts == 0

    # Out-of-window row stays unchanged
    old = await storage.get_mfa_challenge(out_of_window.challenge_id)
    assert old is not None
    assert old.failed_attempts == 1


@pytest.mark.unit
async def test_clear_failures_returns_zero_when_clean(storage: BaseRepository) -> None:
    assert (
        await storage.clear_mfa_failures(
            user_id=uuid4(),
            since=_NOW - timedelta(minutes=15),
        )
        == 0
    )
