# SPDX-License-Identifier: AGPL-3.0-or-later
"""Storage tests for the M9.A4 ``personal_access_token`` table (BaseRepository).

Create / get / by-hash / list+page / count / revoke / touch through the
abstract repo per CLAUDE.md §2.3 Rule 2 (no direct backend import).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from eyenet.contracts.auth import PersonalAccessTokenRow
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _mint(
    storage: BaseRepository,
    *,
    user_id: UUID,
    name: str = "ci",
    scopes: list[str] | None = None,
    created_at: datetime = _NOW,
    expires_at: datetime | None = None,
) -> PersonalAccessTokenRow:
    return await storage.create_personal_access_token(
        user_id=user_id,
        name=name,
        prefix=uuid4().hex[:22],
        hash_value=uuid4().hex + uuid4().hex,  # 64 hex chars, unique
        scopes=scopes if scopes is not None else ["read:metrics"],
        created_at=created_at,
        expires_at=expires_at,
    )


@pytest.mark.unit
async def test_create_get_and_by_hash_round_trip(storage: BaseRepository) -> None:
    user_id = uuid4()
    row = await storage.create_personal_access_token(
        user_id=user_id,
        name="scrape",
        prefix="p" * 22,
        hash_value="d" * 64,
        scopes=["read:metrics"],
        created_at=_NOW,
    )
    assert isinstance(row, PersonalAccessTokenRow)
    assert row.scopes == ["read:metrics"]
    assert row.revoked_at is None
    assert row.last_used_at is None

    by_id = await storage.get_personal_access_token(row.token_id)
    assert by_id is not None and by_id.token_id == row.token_id

    by_hash = await storage.get_personal_access_token_by_hash("d" * 64)
    assert by_hash is not None and by_hash.token_id == row.token_id


@pytest.mark.unit
async def test_get_unknown_returns_none(storage: BaseRepository) -> None:
    assert await storage.get_personal_access_token(uuid4()) is None
    assert await storage.get_personal_access_token_by_hash("0" * 64) is None


@pytest.mark.unit
async def test_list_newest_first_and_offset(storage: BaseRepository) -> None:
    user_id = uuid4()
    rows = [
        await _mint(storage, user_id=user_id, name=f"t{i}", created_at=_NOW + timedelta(minutes=i))
        for i in range(3)
    ]
    # newest (largest created_at) first
    page = await storage.list_personal_access_tokens(user_id=user_id, limit=2, offset=0)
    assert [r.token_id for r in page] == [rows[2].token_id, rows[1].token_id]

    second = await storage.list_personal_access_tokens(user_id=user_id, limit=2, offset=2)
    assert [r.token_id for r in second] == [rows[0].token_id]


@pytest.mark.unit
async def test_list_scoped_to_user(storage: BaseRepository) -> None:
    a, b = uuid4(), uuid4()
    await _mint(storage, user_id=a)
    await _mint(storage, user_id=b)
    page = await storage.list_personal_access_tokens(user_id=a, limit=50)
    assert len(page) == 1
    assert page[0].user_id == a


@pytest.mark.unit
async def test_count(storage: BaseRepository) -> None:
    user_id = uuid4()
    assert await storage.count_personal_access_tokens(user_id=user_id) == 0
    for _ in range(3):
        await _mint(storage, user_id=user_id)
    assert await storage.count_personal_access_tokens(user_id=user_id) == 3


@pytest.mark.unit
async def test_revoke_sets_timestamp_and_is_idempotent(storage: BaseRepository) -> None:
    row = await _mint(storage, user_id=uuid4())
    first = await storage.revoke_personal_access_token(
        token_id=row.token_id,
        revoked_at=_NOW + timedelta(minutes=1),
    )
    assert first.revoked_at == _NOW + timedelta(minutes=1)
    # Re-revoke keeps the first timestamp.
    second = await storage.revoke_personal_access_token(
        token_id=row.token_id,
        revoked_at=_NOW + timedelta(minutes=5),
    )
    assert second.revoked_at == _NOW + timedelta(minutes=1)


@pytest.mark.unit
async def test_revoke_unknown_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.revoke_personal_access_token(token_id=uuid4(), revoked_at=_NOW)


@pytest.mark.unit
async def test_touch_last_used_coarsening(storage: BaseRepository) -> None:
    row = await _mint(storage, user_id=uuid4())

    await storage.touch_pat_last_used(token_id=row.token_id, now=_NOW)
    after_first = await storage.get_personal_access_token(row.token_id)
    assert after_first is not None and after_first.last_used_at == _NOW

    # Within the 60s window → no write.
    await storage.touch_pat_last_used(token_id=row.token_id, now=_NOW + timedelta(seconds=30))
    fresh = await storage.get_personal_access_token(row.token_id)
    assert fresh is not None and fresh.last_used_at == _NOW

    # Past the window → updated.
    later = _NOW + timedelta(seconds=120)
    await storage.touch_pat_last_used(token_id=row.token_id, now=later)
    bumped = await storage.get_personal_access_token(row.token_id)
    assert bumped is not None and bumped.last_used_at == later


@pytest.mark.unit
async def test_touch_skips_revoked(storage: BaseRepository) -> None:
    row = await _mint(storage, user_id=uuid4())
    await storage.revoke_personal_access_token(token_id=row.token_id, revoked_at=_NOW)
    await storage.touch_pat_last_used(token_id=row.token_id, now=_NOW + timedelta(hours=1))
    after = await storage.get_personal_access_token(row.token_id)
    assert after is not None and after.last_used_at is None
