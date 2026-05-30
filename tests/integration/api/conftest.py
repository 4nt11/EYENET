# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixtures for tests/integration/api/* — TestClient on an in-memory app."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eyenet.api.app import create_app
from eyenet.api.auth import encrypt_secret, hash_password, load_mfa_key
from eyenet.contracts.enums import SystemUserRole
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def app(storage: BaseRepository, data_dir: Path) -> FastAPI:
    return create_app(storage=storage, data_dir=data_dir)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)


async def _seed(
    storage: BaseRepository,
    *,
    username: str,
    password: str,
    role: SystemUserRole,
    now: datetime,
    is_active: bool = True,
    mfa_secret_encrypted: str | None = None,
) -> UUID:
    user_id = uuid4()
    await storage.put_system_user(
        user_id=user_id,
        username=username,
        display_name=username.title(),
        role=role,
        created_at=now,
        is_active=is_active,
    )
    await storage.put_credential(
        user_id=user_id,
        password_hash=hash_password(password),
        password_updated_at=now,
        mfa_secret_encrypted=mfa_secret_encrypted,
    )
    return user_id


@pytest.fixture
def seed_user(storage: BaseRepository, data_dir: Path, now: datetime):
    """Return an async helper that seeds an active user+credential.

    Pass ``mfa_secret_b32`` to provision an MFA-enrolled user — the
    plaintext is Fernet-encrypted against the same ``mfa_key`` the app
    will load on startup (in this fixture's ``data_dir``).
    """

    async def _make(
        *,
        username: str = "operator",
        password: str = "correct horse battery staple",  # noqa: S107 — fixture default
        role: SystemUserRole = SystemUserRole.ADMIN,
        is_active: bool = True,
        mfa_secret_b32: str | None = None,
    ) -> UUID:
        ciphertext: str | None = None
        if mfa_secret_b32 is not None:
            fernet = load_mfa_key(data_dir)
            ciphertext = encrypt_secret(fernet, mfa_secret_b32)
        return await _seed(
            storage,
            username=username,
            password=password,
            role=role,
            now=now,
            is_active=is_active,
            mfa_secret_encrypted=ciphertext,
        )

    return _make
