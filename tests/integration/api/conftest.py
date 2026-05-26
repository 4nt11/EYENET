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
from eyenet.api.auth import hash_password
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
    )
    return user_id


@pytest.fixture
def seed_user(storage: BaseRepository, now: datetime):
    """Return an async helper that seeds an active user+credential."""

    async def _make(
        *,
        username: str = "operator",
        password: str = "correct horse battery staple",  # noqa: S107 — fixture default, not a real cred
        role: SystemUserRole = SystemUserRole.ADMIN,
        is_active: bool = True,
    ) -> UUID:
        return await _seed(
            storage,
            username=username,
            password=password,
            role=role,
            now=now,
            is_active=is_active,
        )

    return _make
