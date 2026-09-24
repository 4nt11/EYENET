# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the QR-login handlers (gate + wiring)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from telethon.sessions import StringSession

from eyenet.api.auth._qr_login import QrLoginRegistry
from eyenet.api.deps import CurrentUser, ResourceNotFound, ScopeForbidden
from eyenet.api.v1.identities.api_qr_password import identities_qr_password
from eyenet.api.v1.identities.api_qr_start import identities_qr_start
from eyenet.api.v1.identities.api_qr_status import identities_qr_status
from eyenet.api.v1.schemas.qr_login import QrLoginStartRequest, QrPasswordRequest
from eyenet.contracts.enums import SourceKind, SystemUserRole
from eyenet.crypto import load_session_key
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


class _FakeQr:
    url = "tg://login?token=fake"

    async def wait(self, timeout=None):  # noqa: ASYNC109 — mirrors telethon QRLogin.wait
        return object()

    async def recreate(self):
        return self


class _FakeClient:
    def __init__(self) -> None:
        self.session = StringSession()

    async def connect(self) -> None: ...
    async def qr_login(self) -> _FakeQr:
        return _FakeQr()

    async def sign_in(self, *, password: str): ...
    async def disconnect(self) -> None: ...


def _fake_factory(session, api_id, api_hash, proxy):
    return _FakeClient()


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _user(role: SystemUserRole = SystemUserRole.ADMIN) -> CurrentUser:
    return CurrentUser(
        user_id=uuid4(),
        username="op",
        role=role,
        effective_scopes=frozenset({"write:identity"}),
        token_expires_at=None,
    )


def _registry(storage: BaseRepository, tmp_path: Path) -> QrLoginRegistry:
    return QrLoginRegistry(
        storage=storage,
        session_key=load_session_key(tmp_path),
        data_dir=tmp_path,
        client_factory=_fake_factory,
    )


async def _tg_source(storage: BaseRepository):
    return await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=datetime.now(tz=UTC)
    )


def _body(source_id) -> QrLoginStartRequest:
    return QrLoginStartRequest(
        name="tg_qr", source_id=source_id, telegram_api_id=42, telegram_api_hash="h"
    )


@pytest.mark.unit
async def test_start_non_admin_forbidden(storage: BaseRepository, tmp_path: Path) -> None:
    with pytest.raises(ScopeForbidden):
        await identities_qr_start(
            body=_body(await _tg_source(storage)),
            current_user=_user(SystemUserRole.ANALYST),
            storage=storage,
            registry=_registry(storage, tmp_path),
        )


@pytest.mark.unit
async def test_start_unknown_source_404(storage: BaseRepository, tmp_path: Path) -> None:
    with pytest.raises(ResourceNotFound):
        await identities_qr_start(
            body=_body(uuid4()),
            current_user=_user(),
            storage=storage,
            registry=_registry(storage, tmp_path),
        )


@pytest.mark.unit
async def test_start_returns_challenge(storage: BaseRepository, tmp_path: Path) -> None:
    reg = _registry(storage, tmp_path)
    challenge = await identities_qr_start(
        body=_body(await _tg_source(storage)),
        current_user=_user(),
        storage=storage,
        registry=reg,
    )
    assert challenge.qr_url.startswith("tg://login")
    assert challenge.status == "pending_scan"
    # let the driver finish so we don't leak a task
    state = reg.get(challenge.login_id, owner=next(iter(reg._logins.values())).user_id)
    if state and state.driver_task:
        await state.driver_task


@pytest.mark.unit
async def test_status_wrong_owner_404(storage: BaseRepository, tmp_path: Path) -> None:
    with pytest.raises(ResourceNotFound):
        await identities_qr_status(
            login_id=uuid4(),
            current_user=_user(),
            registry=_registry(storage, tmp_path),
        )


@pytest.mark.unit
async def test_password_unknown_login_404(storage: BaseRepository, tmp_path: Path) -> None:
    with pytest.raises(ResourceNotFound):
        await identities_qr_password(
            login_id=uuid4(),
            body=QrPasswordRequest(password="x"),
            current_user=_user(),
            registry=_registry(storage, tmp_path),
        )
