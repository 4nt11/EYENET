# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for POST /v1/identities (M9.F coverage pattern).

The handler is called as a plain coroutine with an in-memory repo + constructed
CurrentUser — ASGI routing is exercised by integration tests but coverage can't
trace it. Verifies: admin-gate, source resolution, size cap, blob validation,
the encrypted-at-rest write, and that no secret crosses the response surface.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from telethon.crypto import AuthKey
from telethon.sessions import SQLiteSession

from eyenet.api.deps import CurrentUser, ResourceNotFound, ScopeForbidden
from eyenet.api.v1.identities.api_create_identity import identities_create
from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts.enums import SourceKind, SystemUserRole
from eyenet.crypto import decrypt_session, load_session_key
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _audit(storage: BaseRepository) -> AuditEmitter:
    return AuditEmitter(
        BusEnvelopePublisher(MemoryBus()), storage, service="api", instance_id="api-0"
    )


def _user(role: SystemUserRole = SystemUserRole.ADMIN) -> CurrentUser:
    return CurrentUser(
        user_id=uuid4(),
        username="op",
        role=role,
        effective_scopes=frozenset({"write:identity"}),
        token_expires_at=None,
    )


def _session_blob(tmp_path: Path) -> bytes:
    name = str(tmp_path / "mint")
    sess = SQLiteSession(name)
    sess.set_dc(2, "149.154.167.51", 443)
    sess.auth_key = AuthKey(bytes(range(256)))
    sess.save()
    sess.close()
    return (tmp_path / "mint.session").read_bytes()


def _upload(blob: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(blob), filename="a.session")


async def _telegram_source(storage: BaseRepository):
    return await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=datetime.now(tz=UTC)
    )


async def _call(storage: BaseRepository, tmp_path: Path, **overrides: object):
    kwargs: dict[str, object] = {
        "current_user": _user(),
        "storage": storage,
        "audit": _audit(storage),
        "data_dir": tmp_path,
        "session_key": load_session_key(tmp_path),
        "session": _upload(_session_blob(tmp_path)),
        "name": "tg_alpha",
        "source_id": await _telegram_source(storage),
        "telegram_api_id": 42,
        "telegram_api_hash": "deadbeef",
        "monitor_groups": "@a, @b",
        "cooldown_seconds": 21_600,
        "proxy_uri": None,
        "role": None,  # exercise the default at the call site below
        "notes": None,
    }
    kwargs.update(overrides)
    # role default is applied by FastAPI at the ASGI layer; supply it here.
    if kwargs["role"] is None:
        from eyenet.contracts.enums import IdentityRole

        kwargs["role"] = IdentityRole.MONITOR
    return await identities_create(**kwargs)  # type: ignore[arg-type]


@pytest.mark.unit
async def test_happy_path_returns_201_detail_without_secrets(
    storage: BaseRepository, tmp_path: Path
) -> None:
    detail = await _call(storage, tmp_path)

    assert detail.name == "tg_alpha"
    # No secret ever crosses the read surface.
    assert not hasattr(detail, "session_path")
    assert not hasattr(detail, "source_config")

    # Persisted row carries the encrypted blob + source_config; blob is ciphertext.
    row = await storage.get_identity(detail.identity_id)
    assert row is not None
    assert row.source_config == {
        "telegram_api_id": 42,
        "telegram_api_hash": "deadbeef",
        "monitor_groups": ["@a", "@b"],
    }
    on_disk = Path(row.session_path).read_bytes()
    assert on_disk[:6] != b"SQLite"
    key = load_session_key(tmp_path)
    assert decrypt_session(key, on_disk)  # decrypts back to a StringSession string


@pytest.mark.unit
async def test_non_admin_is_forbidden(storage: BaseRepository, tmp_path: Path) -> None:
    with pytest.raises(ScopeForbidden):
        await _call(storage, tmp_path, current_user=_user(SystemUserRole.ANALYST))


@pytest.mark.unit
async def test_oversize_is_413(storage: BaseRepository, tmp_path: Path) -> None:
    big = _upload(b"\x00" * (1 * 1024 * 1024 + 1))
    with pytest.raises(HTTPException) as ei:
        await _call(storage, tmp_path, session=big)
    assert ei.value.status_code == 413


@pytest.mark.unit
async def test_garbage_blob_is_422(storage: BaseRepository, tmp_path: Path) -> None:
    with pytest.raises(RequestValidationError):
        await _call(storage, tmp_path, session=_upload(b"not a sqlite db"))


@pytest.mark.unit
async def test_unknown_source_is_404(storage: BaseRepository, tmp_path: Path) -> None:
    with pytest.raises(ResourceNotFound):
        await _call(storage, tmp_path, source_id=uuid4())


@pytest.mark.unit
async def test_telegram_requires_api_credentials(storage: BaseRepository, tmp_path: Path) -> None:
    with pytest.raises(RequestValidationError):
        await _call(storage, tmp_path, telegram_api_id=None)
