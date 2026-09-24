# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-memory QR-login registry + per-login driver (API_PLAN §3.4 extension).

A Telegram QR login is stateful and multi-step (show QR -> wait for the phone to
scan -> optional 2FA password -> mint the session), so it cannot be served
statelessly: a LIVE Telethon client must stay open across several HTTP requests.
This module holds those live clients in a process-local registry keyed by a
``login_id``, with ONE background driver task per login running the Telethon
dance. HTTP handlers only read state and poke it (feed the 2FA password via an
``asyncio.Event``).

Process-local + single-worker by design (mirrors ``eyenet.api.auth._cache``):
start and its poll/2FA follow-ups MUST land on the same process. A login lost on
API restart is acceptable — the operator restarts it.

The reaper (driven by the app lifespan) disconnects + evicts abandoned/expired
clients; passive TTL eviction cannot run the async ``client.disconnect()`` a live
MTProto connection needs.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, cast
from uuid import UUID, uuid4

from telethon import TelegramClient
from telethon.errors import PasswordHashInvalidError, SessionPasswordNeededError
from telethon.sessions import StringSession

from eyenet.identity_pool._provision import provision_identity_from_session
from eyenet.telemetry.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from cryptography.fernet import Fernet

    from eyenet.contracts.enums import IdentityRole
    from eyenet.storage.repository import BaseRepository
    from eyenet.telemetry.audit import AuditEmitter

_log = get_logger()

# A login lives at most this long end-to-end; the QR token itself is refreshed
# well before its ~30s server expiry; the 2FA step gets its own window; terminal
# states are retained briefly so the poll can read the result before reaping.
_LOGIN_TTL = timedelta(minutes=5)
_QR_REFRESH_SECONDS = 25.0
_PASSWORD_TTL_SECONDS = 180.0
_REAP_INTERVAL_SECONDS = 30.0
_TERMINAL_RETAIN = timedelta(seconds=120)


class QrLoginStatus(StrEnum):
    PENDING_SCAN = "pending_scan"
    PASSWORD_NEEDED = "password_needed"
    COMPLETE = "complete"
    ERROR = "error"
    EXPIRED = "expired"


_TERMINAL = frozenset({QrLoginStatus.COMPLETE, QrLoginStatus.ERROR, QrLoginStatus.EXPIRED})


class _QrClient(Protocol):
    """The slice of the Telethon client the driver uses (eases faking in tests)."""

    async def connect(self) -> None: ...
    async def qr_login(self) -> Any: ...
    async def sign_in(self, *, password: str) -> Any: ...
    async def disconnect(self) -> Any: ...
    @property
    def session(self) -> Any: ...


# (session, api_id, api_hash, proxy) -> client. Real default builds a Telethon
# client on a portable StringSession; tests inject a fake.
def _default_client_factory(session: Any, api_id: int, api_hash: str, proxy: Any) -> _QrClient:
    return cast("_QrClient", TelegramClient(session, api_id, api_hash, proxy=proxy))


@dataclass
class QrLoginState:
    """One in-flight QR login. Mutated only by its driver + the password poke."""

    login_id: UUID
    user_id: UUID  # owner: only this operator may poll/submit
    client: _QrClient
    status: QrLoginStatus
    qr_url: str
    created_at: datetime
    # provisioning metadata captured at start()
    name: str
    source_id: UUID
    source_config: dict[str, object]
    role: IdentityRole
    cooldown_seconds: int
    proxy_uri: str | None
    notes: str | None
    password_event: asyncio.Event = field(default_factory=asyncio.Event)
    password: str | None = None
    identity_id: UUID | None = None
    error: str | None = None
    driver_task: asyncio.Task[None] | None = None

    @property
    def expires_at(self) -> datetime:
        return self.created_at + _LOGIN_TTL


class QrLoginRegistry:
    """Process-local registry of in-flight QR logins + their live clients."""

    def __init__(
        self,
        *,
        storage: BaseRepository,
        session_key: Fernet,
        data_dir: Path,
        audit: AuditEmitter | None = None,
        client_factory: Callable[..., _QrClient] = _default_client_factory,
    ) -> None:
        self._storage = storage
        self._session_key = session_key
        self._data_dir = data_dir
        self._audit = audit
        self._client_factory = client_factory
        self._logins: dict[UUID, QrLoginState] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        *,
        user_id: UUID,
        api_id: int,
        api_hash: str,
        name: str,
        source_id: UUID,
        source_config: dict[str, object],
        role: IdentityRole,
        cooldown_seconds: int,
        proxy_uri: str | None,
        notes: str | None,
    ) -> QrLoginState:
        """Open a live client, mint the first QR, and launch its driver task."""
        proxy = _parse_proxy(proxy_uri)
        client = self._client_factory(StringSession(), api_id, api_hash, proxy)
        await client.connect()
        qr = await client.qr_login()
        state = QrLoginState(
            login_id=uuid4(),
            user_id=user_id,
            client=client,
            status=QrLoginStatus.PENDING_SCAN,
            qr_url=qr.url,
            created_at=datetime.now(tz=UTC),
            name=name,
            source_id=source_id,
            source_config=source_config,
            role=role,
            cooldown_seconds=cooldown_seconds,
            proxy_uri=proxy_uri,
            notes=notes,
        )
        state.driver_task = asyncio.create_task(self._drive(state, qr))
        async with self._lock:
            self._logins[state.login_id] = state
        return state

    def get(self, login_id: UUID, *, owner: UUID) -> QrLoginState | None:
        """Return the login iff it exists and is owned by ``owner`` (else None)."""
        state = self._logins.get(login_id)
        if state is None or state.user_id != owner:
            return None
        return state

    async def submit_password(
        self, login_id: UUID, *, owner: UUID, password: str
    ) -> QrLoginState | None:
        state = self.get(login_id, owner=owner)
        if state is None:
            return None
        if state.status is QrLoginStatus.PASSWORD_NEEDED:
            state.password = password
            state.password_event.set()
        return state

    # -- driver -----------------------------------------------------------

    async def _drive(self, state: QrLoginState, qr: Any) -> None:
        try:
            await self._run_login(state, qr)
        except Exception as exc:
            state.status = QrLoginStatus.ERROR
            state.error = "login_failed"
            _log.warning("qr_login.error", login_id=str(state.login_id), error=str(exc))
        finally:
            with contextlib.suppress(Exception):
                await state.client.disconnect()

    async def _run_login(self, state: QrLoginState, qr: Any) -> None:
        # Scan loop: refresh the QR token before it expires, until scanned or TTL.
        while True:
            remaining = (state.expires_at - datetime.now(tz=UTC)).total_seconds()
            if remaining <= 0:
                state.status = QrLoginStatus.EXPIRED
                return
            try:
                await qr.wait(timeout=min(_QR_REFRESH_SECONDS, remaining))
                break  # scanned, no 2FA
            except TimeoutError:
                qr = await qr.recreate()
                state.qr_url = qr.url
            except SessionPasswordNeededError:
                if not await self._await_password(state):
                    return  # status already set (expired/error)
                break
        await self._mint(state)

    async def _await_password(self, state: QrLoginState) -> bool:
        state.status = QrLoginStatus.PASSWORD_NEEDED
        try:
            await asyncio.wait_for(state.password_event.wait(), timeout=_PASSWORD_TTL_SECONDS)
        except TimeoutError:
            state.status = QrLoginStatus.EXPIRED
            return False
        try:
            await state.client.sign_in(password=state.password or "")
            return True
        except PasswordHashInvalidError:
            state.status = QrLoginStatus.ERROR
            state.error = "invalid_2fa_password"
            return False
        finally:
            state.password = None

    async def _mint(self, state: QrLoginState) -> None:
        session_string = str(StringSession.save(state.client.session))
        try:
            identity = await provision_identity_from_session(
                storage=self._storage,
                session_key=self._session_key,
                data_dir=self._data_dir,
                name=state.name,
                source_id=state.source_id,
                session_string=session_string,
                source_config=state.source_config,
                role=state.role,
                cooldown_seconds=state.cooldown_seconds,
                proxy_uri=state.proxy_uri,
                notes=state.notes,
            )
        except Exception as exc:
            state.status = QrLoginStatus.ERROR
            state.error = f"provision_failed: {exc}"
            _log.warning("qr_login.provision_failed", login_id=str(state.login_id), error=str(exc))
            return
        state.identity_id = identity.id
        state.status = QrLoginStatus.COMPLETE
        if self._audit is not None:
            await self._audit.emit(
                event="identity.provisioned",
                subject_kind="identity",
                subject_id=identity.id,
                system_user_id=state.user_id,
                payload={
                    "name": state.name,
                    "source_id": str(state.source_id),
                    "via": "qr_login",
                },
            )

    # -- lifecycle --------------------------------------------------------

    async def reap_loop(self) -> None:
        """Periodically disconnect + evict abandoned/expired/aged-out logins."""
        while True:
            await asyncio.sleep(_REAP_INTERVAL_SECONDS)
            with contextlib.suppress(Exception):
                await self._reap_once()

    async def _reap_once(self) -> None:
        now = datetime.now(tz=UTC)
        async with self._lock:
            dead = [lid for lid, s in self._logins.items() if self._reapable(s, now)]
            for lid in dead:
                state = self._logins.pop(lid)
                if state.driver_task is not None:
                    state.driver_task.cancel()
                with contextlib.suppress(Exception):
                    await state.client.disconnect()

    @staticmethod
    def _reapable(state: QrLoginState, now: datetime) -> bool:
        age = now - state.created_at
        if state.status in _TERMINAL:
            return age > _TERMINAL_RETAIN  # keep briefly so the poll can read it
        return age > _LOGIN_TTL + timedelta(seconds=30)  # safety net for stuck drivers

    async def shutdown(self) -> None:
        """Cancel every driver + disconnect every live client (app shutdown)."""
        async with self._lock:
            states = list(self._logins.values())
            self._logins.clear()
        for state in states:
            if state.driver_task is not None:
                state.driver_task.cancel()
            with contextlib.suppress(Exception):
                await state.client.disconnect()


def _parse_proxy(proxy_uri: str | None) -> Any:
    """Reuse the collector's proxy parsing so QR + collector treat proxies alike."""
    if not proxy_uri:
        return None
    from eyenet.collectors.telegram.real import _parse_proxy as _pp  # noqa: PLC0415

    return _pp(proxy_uri)


__all__ = ["QrLoginRegistry", "QrLoginState", "QrLoginStatus"]
