"""Storage tests for M9.A1 auth tables (BaseRepository abstraction).

Covers credential, refresh_token, jwt_denylist, system_user_scope CRUD via
the abstract repository. SQLite-impl-specific CHECK probes live in
``test_auth_sqlmodel.py`` per CLAUDE.md §2.3 Rule 2.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from eyenet.contracts.auth import (
    JwtDenylistRow,
    RefreshTokenRow,
    SystemUserCredentialRow,
    SystemUserScopeRow,
)
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 5, 25, tzinfo=UTC)
_LATER = _NOW + timedelta(days=1)
_EXP = _NOW + timedelta(days=30)
_HASH_A = "a" * 64
_HASH_B = "b" * 64


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


# --- Credentials ---------------------------------------------------------


@pytest.mark.unit
async def test_credential_round_trip(storage: BaseRepository) -> None:
    user_id = uuid4()
    row = await storage.put_credential(
        user_id=user_id,
        password_hash="$argon2id$v=19$opaque-stub",
        password_updated_at=_NOW,
    )
    assert isinstance(row, SystemUserCredentialRow)
    assert row.user_id == user_id
    assert row.password_hash == "$argon2id$v=19$opaque-stub"
    assert row.mfa_secret_encrypted is None

    fetched = await storage.get_credential(user_id)
    assert fetched is not None
    assert fetched.user_id == user_id
    assert fetched.password_updated_at == _NOW


@pytest.mark.unit
async def test_get_credential_returns_none_for_unknown(storage: BaseRepository) -> None:
    assert await storage.get_credential(uuid4()) is None


@pytest.mark.unit
async def test_put_credential_is_upsert(storage: BaseRepository) -> None:
    user_id = uuid4()
    await storage.put_credential(
        user_id=user_id,
        password_hash="hash1",
        password_updated_at=_NOW,
    )
    # Second put with same user_id updates, doesn't insert a duplicate.
    updated = await storage.put_credential(
        user_id=user_id,
        password_hash="hash2",
        password_updated_at=_LATER,
        mfa_secret_encrypted="age-encrypted-blob",
    )
    assert updated.password_hash == "hash2"
    assert updated.password_updated_at == _LATER
    assert updated.mfa_secret_encrypted == "age-encrypted-blob"


@pytest.mark.unit
async def test_delete_credential(storage: BaseRepository) -> None:
    user_id = uuid4()
    await storage.put_credential(
        user_id=user_id,
        password_hash="x",
        password_updated_at=_NOW,
    )
    await storage.delete_credential(user_id)
    assert await storage.get_credential(user_id) is None


@pytest.mark.unit
async def test_delete_credential_unknown_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.delete_credential(uuid4())


# --- Refresh tokens ------------------------------------------------------


@pytest.mark.unit
async def test_refresh_token_round_trip(storage: BaseRepository) -> None:
    user_id = uuid4()
    row = await storage.create_refresh_token(
        user_id=user_id,
        hash_value=_HASH_A,
        issued_at=_NOW,
        expires_at=_EXP,
    )
    assert isinstance(row, RefreshTokenRow)
    assert row.user_id == user_id
    assert row.hash == _HASH_A
    assert row.revoked_at is None
    assert row.replaced_by is None

    by_hash = await storage.get_refresh_token_by_hash(_HASH_A)
    assert by_hash is not None
    assert by_hash.token_id == row.token_id

    by_id = await storage.get_refresh_token(row.token_id)
    assert by_id is not None
    assert by_id.hash == _HASH_A


@pytest.mark.unit
async def test_refresh_token_lookup_returns_none_for_unknown(
    storage: BaseRepository,
) -> None:
    assert await storage.get_refresh_token_by_hash("z" * 64) is None
    assert await storage.get_refresh_token(uuid4()) is None


@pytest.mark.unit
async def test_revoke_refresh_token_without_replacement(
    storage: BaseRepository,
) -> None:
    # Logout case: revoke a refresh token without a replacement.
    row = await storage.create_refresh_token(
        user_id=uuid4(),
        hash_value=_HASH_A,
        issued_at=_NOW,
        expires_at=_EXP,
    )
    revoked = await storage.revoke_refresh_token(
        token_id=row.token_id,
        revoked_at=_LATER,
    )
    assert revoked.revoked_at == _LATER
    assert revoked.replaced_by is None


@pytest.mark.unit
async def test_refresh_token_rotation_chain(storage: BaseRepository) -> None:
    # /refresh case: mint a new token then revoke the old one with replaced_by.
    user_id = uuid4()
    first = await storage.create_refresh_token(
        user_id=user_id,
        hash_value=_HASH_A,
        issued_at=_NOW,
        expires_at=_EXP,
    )
    second = await storage.create_refresh_token(
        user_id=user_id,
        hash_value=_HASH_B,
        issued_at=_LATER,
        expires_at=_EXP + timedelta(days=1),
    )
    revoked = await storage.revoke_refresh_token(
        token_id=first.token_id,
        revoked_at=_LATER,
        replaced_by=second.token_id,
    )
    assert revoked.replaced_by == second.token_id
    assert revoked.revoked_at == _LATER


@pytest.mark.unit
async def test_revoke_refresh_token_unknown_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.revoke_refresh_token(token_id=uuid4(), revoked_at=_NOW)


# --- JWT denylist --------------------------------------------------------


@pytest.mark.unit
async def test_deny_jwt_and_check(storage: BaseRepository) -> None:
    jti = uuid4()
    row = await storage.deny_jwt(
        jti=jti,
        user_id=uuid4(),
        denied_at=_NOW,
        expires_at=_NOW + timedelta(minutes=15),
    )
    assert isinstance(row, JwtDenylistRow)
    assert await storage.is_jwt_denylisted(jti) is True


@pytest.mark.unit
async def test_is_jwt_denylisted_false_for_unknown(storage: BaseRepository) -> None:
    assert await storage.is_jwt_denylisted(uuid4()) is False


@pytest.mark.unit
async def test_deny_jwt_idempotent(storage: BaseRepository) -> None:
    jti = uuid4()
    user_id = uuid4()
    first = await storage.deny_jwt(
        jti=jti,
        user_id=user_id,
        denied_at=_NOW,
        expires_at=_NOW + timedelta(minutes=15),
    )
    # Re-deny should return the existing row, not raise IntegrityError.
    second = await storage.deny_jwt(
        jti=jti,
        user_id=user_id,
        denied_at=_LATER,
        expires_at=_LATER + timedelta(minutes=15),
    )
    # The returned row reflects the original entry, not the second call's
    # later timestamps.
    assert first.denied_at == _NOW
    assert second.denied_at == _NOW


# --- Scope grants --------------------------------------------------------


@pytest.mark.unit
async def test_grant_scope_round_trip(storage: BaseRepository) -> None:
    user_id = uuid4()
    admin_id = uuid4()
    row = await storage.grant_scope(
        user_id=user_id,
        scope="read:metrics",
        granted_at=_NOW,
        granted_by_user_id=admin_id,
    )
    assert isinstance(row, SystemUserScopeRow)
    assert row.scope == "read:metrics"

    listed = await storage.list_explicit_scopes(user_id)
    assert len(listed) == 1
    assert listed[0].scope == "read:metrics"


@pytest.mark.unit
async def test_list_explicit_scopes_empty_for_unknown_user(
    storage: BaseRepository,
) -> None:
    assert await storage.list_explicit_scopes(uuid4()) == []


@pytest.mark.unit
async def test_grant_scope_idempotent(storage: BaseRepository) -> None:
    user_id = uuid4()
    admin_id = uuid4()
    first = await storage.grant_scope(
        user_id=user_id,
        scope="read:metrics",
        granted_at=_NOW,
        granted_by_user_id=admin_id,
    )
    # Re-grant returns existing row; granted_at stays at the original value.
    second = await storage.grant_scope(
        user_id=user_id,
        scope="read:metrics",
        granted_at=_LATER,
        granted_by_user_id=admin_id,
    )
    assert first.granted_at == _NOW
    assert second.granted_at == _NOW

    # And there's only one row in the table for this (user, scope).
    listed = await storage.list_explicit_scopes(user_id)
    assert len(listed) == 1


@pytest.mark.unit
async def test_revoke_scope(storage: BaseRepository) -> None:
    user_id = uuid4()
    await storage.grant_scope(
        user_id=user_id,
        scope="read:metrics",
        granted_at=_NOW,
        granted_by_user_id=uuid4(),
    )
    await storage.revoke_scope(user_id=user_id, scope="read:metrics")
    assert await storage.list_explicit_scopes(user_id) == []


@pytest.mark.unit
async def test_revoke_scope_unknown_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.revoke_scope(user_id=uuid4(), scope="read:metrics")


@pytest.mark.unit
async def test_list_explicit_scopes_multiple_grants(storage: BaseRepository) -> None:
    user_id = uuid4()
    admin_id = uuid4()
    await storage.grant_scope(
        user_id=user_id,
        scope="read:metrics",
        granted_at=_NOW,
        granted_by_user_id=admin_id,
    )
    await storage.grant_scope(
        user_id=user_id,
        scope="read:restricted",
        granted_at=_LATER,
        granted_by_user_id=admin_id,
    )
    listed = await storage.list_explicit_scopes(user_id)
    scopes = {r.scope for r in listed}
    assert scopes == {"read:metrics", "read:restricted"}


@pytest.mark.unit
async def test_user_ids_are_isolated(storage: BaseRepository) -> None:
    # Grants for user A must not leak into user B's list.
    user_a = uuid4()
    user_b = uuid4()
    admin_id = uuid4()
    await storage.grant_scope(
        user_id=user_a,
        scope="read:metrics",
        granted_at=_NOW,
        granted_by_user_id=admin_id,
    )
    await storage.grant_scope(
        user_id=user_b,
        scope="read:restricted",
        granted_at=_NOW,
        granted_by_user_id=admin_id,
    )
    assert {r.scope for r in await storage.list_explicit_scopes(user_a)} == {
        "read:metrics",
    }
    assert {r.scope for r in await storage.list_explicit_scopes(user_b)} == {
        "read:restricted",
    }


# --- Contract shape sanity ----------------------------------------------


@pytest.mark.unit
async def test_credential_row_contract_shape(storage: BaseRepository) -> None:
    user_id = uuid4()
    row = await storage.put_credential(
        user_id=user_id,
        password_hash="$argon2id$opaque",
        password_updated_at=_NOW,
        mfa_secret_encrypted="age-blob",
    )
    dumped = row.model_dump()
    assert dumped["user_id"] == user_id
    assert dumped["mfa_secret_encrypted"] == "age-blob"
    assert dumped["password_updated_at"].tzinfo is not None


@pytest.mark.unit
def test_refresh_token_hash_must_be_64_chars() -> None:
    # Pydantic validator at the contract layer rejects too-short hashes.
    with pytest.raises(ValueError, match=r"string_too_short|hash"):
        RefreshTokenRow(
            token_id=uuid4(),
            user_id=uuid4(),
            hash="tooShort",  # not 64 chars
            issued_at=_NOW,
            expires_at=_EXP,
        )
