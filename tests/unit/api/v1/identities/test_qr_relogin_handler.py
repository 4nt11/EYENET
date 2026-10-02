# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for POST /v1/identities/{id}/qr-login (QR re-login)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.exceptions import RequestValidationError
from telethon.sessions import StringSession

from eyenet.api.deps import CurrentUser, ResourceNotFound, ScopeForbidden
from eyenet.api.v1.identities.api_qr_relogin import identities_qr_relogin
from eyenet.contracts.enums import SourceKind, SystemUserRole
from eyenet.crypto import load_session_key
from eyenet.identity_pool._provision import provision_identity_from_session
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


class _FakeStatus:
    value = "pending_scan"


@dataclass
class _FakeState:
    login_id: UUID
    qr_url: str
    status: _FakeStatus

    @property
    def expires_at(self) -> datetime:
        return datetime.now(tz=UTC) + timedelta(minutes=2)


class _FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def start(self, **kwargs: object):
        self.calls.append(kwargs)
        return _FakeState(login_id=uuid4(), qr_url="tg://login?token=x", status=_FakeStatus())


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


async def _tg_identity(storage: BaseRepository, tmp_path: Path, cfg: dict):
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=datetime.now(tz=UTC)
    )
    return await provision_identity_from_session(
        storage=storage,
        session_key=load_session_key(tmp_path),
        data_dir=tmp_path,
        name="tg_main",
        source_id=src,
        session_string=str(StringSession.save(StringSession())),
        source_config=cfg,
    )


@pytest.mark.unit
async def test_relogin_happy_path_starts_with_target(
    storage: BaseRepository, tmp_path: Path
) -> None:
    ident = await _tg_identity(storage, tmp_path, {"telegram_api_id": 42, "telegram_api_hash": "h"})
    reg = _FakeRegistry()
    challenge = await identities_qr_relogin(
        identity_id=ident.id,
        current_user=_user(),
        storage=storage,
        registry=reg,  # type: ignore[arg-type]
    )
    assert challenge.qr_url.startswith("tg://login")
    # Started in REPLACE mode against this identity, reusing its api creds.
    assert reg.calls[0]["target_identity_id"] == ident.id
    assert reg.calls[0]["api_id"] == 42
    assert reg.calls[0]["api_hash"] == "h"
    assert reg.calls[0]["source_id"] == ident.source_id


@pytest.mark.unit
async def test_relogin_non_admin_forbidden(storage: BaseRepository, tmp_path: Path) -> None:
    ident = await _tg_identity(storage, tmp_path, {"telegram_api_id": 42, "telegram_api_hash": "h"})
    with pytest.raises(ScopeForbidden):
        await identities_qr_relogin(
            identity_id=ident.id,
            current_user=_user(SystemUserRole.ANALYST),
            storage=storage,
            registry=_FakeRegistry(),  # type: ignore[arg-type]
        )


@pytest.mark.unit
async def test_relogin_unknown_identity_404(storage: BaseRepository, tmp_path: Path) -> None:
    with pytest.raises(ResourceNotFound):
        await identities_qr_relogin(
            identity_id=uuid4(),
            current_user=_user(),
            storage=storage,
            registry=_FakeRegistry(),  # type: ignore[arg-type]
        )


@pytest.mark.unit
async def test_relogin_non_telegram_422(storage: BaseRepository, tmp_path: Path) -> None:
    src = await storage.upsert_source(
        kind=SourceKind.FORUM, display_name="forum:x", created_at=datetime.now(tz=UTC)
    )
    from eyenet.identity_pool._provision import provision_identity

    ident = await provision_identity(
        storage=storage,
        session_key=load_session_key(tmp_path),
        data_dir=tmp_path,
        name="f",
        source_id=src,
        source_kind=SourceKind.FORUM,
        secret_blob=b"# Netscape HTTP Cookie File\nh\tFALSE\t/\tFALSE\t1\tsid\tA\n",
        source_config={"forum_base_url": "http://h.onion"},
    )
    with pytest.raises(RequestValidationError):
        await identities_qr_relogin(
            identity_id=ident.id,
            current_user=_user(),
            storage=storage,
            registry=_FakeRegistry(),  # type: ignore[arg-type]
        )


@pytest.mark.unit
async def test_relogin_missing_api_creds_422(storage: BaseRepository, tmp_path: Path) -> None:
    ident = await _tg_identity(storage, tmp_path, {"monitor_groups": []})  # no api_id/hash
    with pytest.raises(RequestValidationError):
        await identities_qr_relogin(
            identity_id=ident.id,
            current_user=_user(),
            storage=storage,
            registry=_FakeRegistry(),  # type: ignore[arg-type]
        )
