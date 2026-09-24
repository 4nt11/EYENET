"""Unit tests for the QR-login registry + driver (no live Telegram — fake client)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from telethon.errors import PasswordHashInvalidError, SessionPasswordNeededError
from telethon.sessions import StringSession

from eyenet.api.auth._qr_login import QrLoginRegistry, QrLoginStatus
from eyenet.contracts.enums import IdentityRole, SourceKind
from eyenet.crypto import load_session_key
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


class _FakeQr:
    """Stands in for telethon's QRLogin. `raise_2fa` makes wait() demand a password."""

    def __init__(self, *, raise_2fa: bool = False) -> None:
        self.url = "tg://login?token=fake"
        self._raise_2fa = raise_2fa
        self.waits = 0

    async def wait(self, timeout: float | None = None) -> object:  # noqa: ASYNC109 — mirrors telethon
        self.waits += 1
        if self._raise_2fa:
            raise SessionPasswordNeededError(request=None)
        return object()  # a "user" — the driver ignores the value

    async def recreate(self) -> _FakeQr:
        return self


class _FakeClient:
    def __init__(self, qr: _FakeQr, *, signin_error: Exception | None = None) -> None:
        self._qr = qr
        self._signin_error = signin_error
        self.session = StringSession()
        self.connected = False
        self.disconnected = False

    async def connect(self) -> None:
        self.connected = True

    async def qr_login(self) -> _FakeQr:
        return self._qr

    async def sign_in(self, *, password: str) -> object:
        if self._signin_error is not None:
            raise self._signin_error
        return object()

    async def disconnect(self) -> None:
        self.disconnected = True


def _factory(qr: _FakeQr, *, signin_error: Exception | None = None):
    def make(session, api_id, api_hash, proxy):
        return _FakeClient(qr, signin_error=signin_error)

    return make


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _source(storage: BaseRepository):
    return await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=datetime.now(tz=UTC)
    )


def _registry(storage, tmp_path, qr, *, signin_error=None) -> QrLoginRegistry:
    return QrLoginRegistry(
        storage=storage,
        session_key=load_session_key(tmp_path),
        data_dir=tmp_path,
        client_factory=_factory(qr, signin_error=signin_error),
    )


async def _start(registry: QrLoginRegistry, storage: BaseRepository, *, name: str, user_id):
    return await registry.start(
        user_id=user_id,
        api_id=42,
        api_hash="hash",
        name=name,
        source_id=await _source(storage),
        source_config={"telegram_api_id": 42, "telegram_api_hash": "hash", "monitor_groups": []},
        role=IdentityRole.MONITOR,
        cooldown_seconds=21_600,
        proxy_uri=None,
        notes=None,
    )


async def _await_status(state, target: QrLoginStatus, timeout: float = 2.0) -> None:  # noqa: ASYNC109
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while state.status != target and loop.time() < deadline:  # noqa: ASYNC110 — poll a bg task
        await asyncio.sleep(0.01)


@pytest.mark.unit
async def test_happy_path_no_2fa_mints_identity(storage: BaseRepository, tmp_path: Path) -> None:
    reg = _registry(storage, tmp_path, _FakeQr())
    user = uuid4()
    state = await _start(reg, storage, name="tg_qr", user_id=user)
    assert state.status is QrLoginStatus.PENDING_SCAN
    assert state.qr_url.startswith("tg://login")

    await state.driver_task  # driver runs to completion
    assert state.status is QrLoginStatus.COMPLETE
    assert state.identity_id is not None
    assert (await storage.get_identity_by_name("tg_qr")) is not None
    assert state.client.disconnected is True  # cleaned up


@pytest.mark.unit
async def test_2fa_path_completes_after_password(storage: BaseRepository, tmp_path: Path) -> None:
    reg = _registry(storage, tmp_path, _FakeQr(raise_2fa=True))
    user = uuid4()
    state = await _start(reg, storage, name="tg_2fa", user_id=user)

    await _await_status(state, QrLoginStatus.PASSWORD_NEEDED)
    assert state.status is QrLoginStatus.PASSWORD_NEEDED

    returned = await reg.submit_password(state.login_id, owner=user, password="hunter2")
    assert returned is not None
    await state.driver_task
    assert state.status is QrLoginStatus.COMPLETE
    assert state.password is None  # cleared, never retained
    assert (await storage.get_identity_by_name("tg_2fa")) is not None


@pytest.mark.unit
async def test_wrong_2fa_password_errors(storage: BaseRepository, tmp_path: Path) -> None:
    reg = _registry(
        storage,
        tmp_path,
        _FakeQr(raise_2fa=True),
        signin_error=PasswordHashInvalidError(request=None),
    )
    user = uuid4()
    state = await _start(reg, storage, name="tg_bad2fa", user_id=user)
    await _await_status(state, QrLoginStatus.PASSWORD_NEEDED)
    await reg.submit_password(state.login_id, owner=user, password="wrong")
    await state.driver_task
    assert state.status is QrLoginStatus.ERROR
    assert state.error == "invalid_2fa_password"


@pytest.mark.unit
async def test_ownership_isolation(storage: BaseRepository, tmp_path: Path) -> None:
    reg = _registry(storage, tmp_path, _FakeQr())
    owner = uuid4()
    state = await _start(reg, storage, name="tg_own", user_id=owner)
    await state.driver_task
    assert reg.get(state.login_id, owner=uuid4()) is None  # different operator
    assert reg.get(state.login_id, owner=owner) is not None


@pytest.mark.unit
async def test_shutdown_disconnects_live_clients(storage: BaseRepository, tmp_path: Path) -> None:
    qr = _FakeQr(raise_2fa=True)  # parks in PASSWORD_NEEDED (client stays live)
    reg = _registry(storage, tmp_path, qr)
    state = await _start(reg, storage, name="tg_live", user_id=uuid4())
    await _await_status(state, QrLoginStatus.PASSWORD_NEEDED)
    await reg.shutdown()
    assert state.client.disconnected is True
