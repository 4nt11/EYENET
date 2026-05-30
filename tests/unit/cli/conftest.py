# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared fixtures for ``eyenet user`` CLI tests (M9.A6).

A `data_dir` + factory-built `storage` typed as `BaseRepository`
([[feedback_use_basereo_abstraction_in_tests]]), and a `seed_user` helper
that writes a profile + credential row (optionally MFA-enrolled, encrypting
the seed under the same `data_dir` key the CLI gate decrypts with).
"""

from __future__ import annotations

import tempfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from eyenet.api.auth import encrypt_secret, hash_password, load_mfa_key
from eyenet.contracts.enums import SystemUserRole
from eyenet.models._base import new_uuid7
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

SeedUser = Callable[..., Awaitable[UUID]]


@pytest.fixture
def data_dir() -> Path:
    return Path(tempfile.mkdtemp())


@pytest.fixture
def storage(data_dir: Path) -> BaseRepository:
    return get_repository(data_dir=data_dir)


@pytest.fixture
def seed_user(data_dir: Path) -> SeedUser:
    """Return an async helper that persists a user + credential row.

    ``mfa_seed`` (a base32 TOTP secret) enrolls MFA by encrypting it under the
    fixture ``data_dir``'s key — the same key the authorizer gate decrypts
    with, so a TOTP step-up round-trips end to end.
    """

    async def _seed(
        storage: BaseRepository,
        *,
        username: str,
        password: str,
        role: SystemUserRole = SystemUserRole.ADMIN,
        mfa_seed: str | None = None,
        with_credential: bool = True,
    ) -> UUID:
        now = datetime.now(tz=UTC)
        user_id = new_uuid7()
        await storage.put_system_user(
            user_id=user_id,
            username=username,
            display_name=username,
            role=role,
            created_at=now,
        )
        # `with_credential=False` leaves a profile row with no credential —
        # the defensive "no credential" branches the gate/commands guard against.
        if with_credential:
            encrypted = (
                encrypt_secret(load_mfa_key(data_dir), mfa_seed) if mfa_seed is not None else None
            )
            await storage.put_credential(
                user_id=user_id,
                password_hash=hash_password(password),
                password_updated_at=now,
                mfa_secret_encrypted=encrypted,
            )
        return user_id

    return _seed
