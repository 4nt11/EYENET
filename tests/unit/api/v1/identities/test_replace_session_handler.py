# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for PUT /v1/identities/{id}/session (M9.F coverage pattern).

Credential rotation: only the encrypted session blob changes. Verifies admin-gate,
identity/source resolution, size cap, blob validation, the in-place swap, old-blob
cleanup, and that no secret crosses the response surface.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError

from eyenet.api.deps import CurrentUser, ResourceNotFound, ScopeForbidden
from eyenet.api.v1.identities.api_replace_identity_session import identities_replace_session
from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts.enums import SourceKind, SystemUserRole
from eyenet.crypto import decrypt_session, load_session_key
from eyenet.identity_pool._provision import provision_identity
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

_COOKIES_A = "# Netscape HTTP Cookie File\nhost.onion\tFALSE\t/\tFALSE\t9999999999\tsid\tAAA\n"
_COOKIES_B = "# Netscape HTTP Cookie File\nhost.onion\tFALSE\t/\tFALSE\t9999999999\tsid\tBBB\n"


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


def _upload(text: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(text.encode()), filename="cookies.txt")


async def _seed_forum_identity(storage: BaseRepository, tmp_path: Path):
    src = await storage.upsert_source(
        kind=SourceKind.FORUM, display_name="forum:pwn", created_at=datetime.now(tz=UTC)
    )
    return await provision_identity(
        storage=storage,
        session_key=load_session_key(tmp_path),
        data_dir=tmp_path,
        name="pwn",
        source_id=src,
        source_kind=SourceKind.FORUM,
        secret_blob=_COOKIES_A.encode(),
        source_config={"forum_base_url": "http://host.onion", "forum_evasion_level": "lurker"},
    )


async def _call(storage: BaseRepository, tmp_path: Path, identity_id, **overrides: object):
    kwargs: dict[str, object] = {
        "identity_id": identity_id,
        "current_user": _user(),
        "storage": storage,
        "audit": _audit(storage),
        "data_dir": tmp_path,
        "session_key": load_session_key(tmp_path),
        "session": _upload(_COOKIES_B),
    }
    kwargs.update(overrides)
    return await identities_replace_session(**kwargs)  # type: ignore[arg-type]


@pytest.mark.unit
async def test_rotates_credential_keeping_config(storage: BaseRepository, tmp_path: Path) -> None:
    row = await _seed_forum_identity(storage, tmp_path)
    old_path = row.session_path

    detail = await _call(storage, tmp_path, row.id)

    assert detail.identity_id == row.id
    assert not hasattr(detail, "session_path")  # no secret on the read surface
    updated = await storage.get_identity(row.id)
    assert updated is not None
    assert updated.session_path != old_path
    assert updated.source_config == {
        "forum_base_url": "http://host.onion",
        "forum_evasion_level": "lurker",
    }  # config untouched
    key = load_session_key(tmp_path)
    assert decrypt_session(key, Path(updated.session_path).read_bytes()) == _COOKIES_B
    assert not Path(old_path).exists()  # old blob cleaned up


@pytest.mark.unit
async def test_non_admin_forbidden(storage: BaseRepository, tmp_path: Path) -> None:
    row = await _seed_forum_identity(storage, tmp_path)
    with pytest.raises(ScopeForbidden):
        await _call(storage, tmp_path, row.id, current_user=_user(SystemUserRole.ANALYST))


@pytest.mark.unit
async def test_unknown_identity_404(storage: BaseRepository, tmp_path: Path) -> None:
    with pytest.raises(ResourceNotFound):
        await _call(storage, tmp_path, uuid4())


@pytest.mark.unit
async def test_oversize_413(storage: BaseRepository, tmp_path: Path) -> None:
    row = await _seed_forum_identity(storage, tmp_path)
    big = UploadFile(file=io.BytesIO(b"x" * (1 * 1024 * 1024 + 1)), filename="cookies.txt")
    with pytest.raises(HTTPException) as ei:
        await _call(storage, tmp_path, row.id, session=big)
    assert ei.value.status_code == 413


@pytest.mark.unit
async def test_garbage_blob_422_leaves_original(storage: BaseRepository, tmp_path: Path) -> None:
    row = await _seed_forum_identity(storage, tmp_path)
    good_path = row.session_path
    with pytest.raises(RequestValidationError):
        await _call(storage, tmp_path, row.id, session=_upload("no cookie rows here"))
    # original credential intact
    key = load_session_key(tmp_path)
    assert decrypt_session(key, Path(good_path).read_bytes()) == _COOKIES_A
