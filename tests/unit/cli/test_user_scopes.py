# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for ``eyenet user scopes {grant,revoke,list}`` (M9.A6).

Exercises the TOTP step-up, the clearance-scope refusal, the granted_by
provenance, the best-effort scopes_changed publish, and the ungated list.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pyotp
import pytest
from cryptography.fernet import Fernet
from nats import errors as nats_errors
from typer.testing import CliRunner

from eyenet.api.auth import generate_secret
from eyenet.cli.main import app
from eyenet.contracts.enums import SystemUserRole
from eyenet.storage.repository import BaseRepository
from tests.unit.cli.conftest import SeedUser

runner = CliRunner()
pytestmark = pytest.mark.unit


def _totp(seed: str) -> str:
    return str(pyotp.TOTP(seed).now())


def test_grant_with_totp_stepup_records_granted_by(
    storage: BaseRepository,
    data_dir: Path,
    seed_user: SeedUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the scopes_changed publish to fail so the best-effort branch is
    # exercised instantly and deterministically, regardless of any local broker.
    async def _refuse(_url: str) -> object:
        raise nats_errors.NoServersError

    monkeypatch.setattr("eyenet.cli.user.NATSBus.connect", _refuse)
    seed = generate_secret()
    asyncio.run(
        seed_user(
            storage,
            username="admin",
            password="adminpw",
            role=SystemUserRole.ADMIN,
            mfa_seed=seed,
        )
    )
    asyncio.run(seed_user(storage, username="bob", password="bobpw", role=SystemUserRole.VIEWER))

    result = runner.invoke(
        app,
        [
            "user",
            "scopes",
            "grant",
            "bob",
            "read:metrics",
            "--as",
            "admin",
            "--data-dir",
            str(data_dir),
        ],
        input=f"adminpw\n{_totp(seed)}\n",
    )
    assert result.exit_code == 0, result.output
    assert "granted to 'bob': read:metrics" in result.output
    # Best-effort cache-eviction publish: unreachable broker → warns, no failure.
    assert "NATS unreachable" in result.output

    async def _check() -> tuple[object, list[str], object]:
        admin = await storage.get_system_user_by_username("admin")
        bob = await storage.get_system_user_by_username("bob")
        assert admin is not None and bob is not None
        rows = await storage.list_explicit_scopes(bob.id)
        return admin.id, [r.scope for r in rows], (rows[0].granted_by_user_id if rows else None)

    admin_id, scopes, granted_by = asyncio.run(_check())
    assert scopes == ["read:metrics"]
    assert granted_by == admin_id


def test_grant_bad_totp_exits_3(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    seed = generate_secret()
    asyncio.run(seed_user(storage, username="admin", password="adminpw", mfa_seed=seed))
    asyncio.run(seed_user(storage, username="bob", password="bobpw", role=SystemUserRole.VIEWER))
    wrong = "000000" if _totp(seed) != "000000" else "111111"
    result = runner.invoke(
        app,
        [
            "user",
            "scopes",
            "grant",
            "bob",
            "read:metrics",
            "--as",
            "admin",
            "--data-dir",
            str(data_dir),
        ],
        input=f"adminpw\n{wrong}\n",
    )
    assert result.exit_code == 3, result.output


def test_grant_clearance_scope_refused_exits_5(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw", role=SystemUserRole.ADMIN))
    asyncio.run(seed_user(storage, username="bob", password="bobpw", role=SystemUserRole.VIEWER))
    result = runner.invoke(
        app,
        [
            "user",
            "scopes",
            "grant",
            "bob",
            "read:classified",
            "--as",
            "admin",
            "--data-dir",
            str(data_dir),
        ],
        input="adminpw\n",
    )
    assert result.exit_code == 5, result.output
    assert "clearance scope" in result.output

    async def _none() -> list[str]:
        bob = await storage.get_system_user_by_username("bob")
        assert bob is not None
        return [r.scope for r in await storage.list_explicit_scopes(bob.id)]

    assert asyncio.run(_none()) == []  # refusal is total — nothing written


def test_grant_unknown_scope_exits_2(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw", role=SystemUserRole.ADMIN))
    asyncio.run(seed_user(storage, username="bob", password="bobpw", role=SystemUserRole.VIEWER))
    result = runner.invoke(
        app,
        [
            "user",
            "scopes",
            "grant",
            "bob",
            "read:flarp",
            "--as",
            "admin",
            "--data-dir",
            str(data_dir),
        ],
        input="adminpw\n",
    )
    assert result.exit_code == 2, result.output
    assert "unknown scope" in result.output


def test_scopes_list_is_ungated_and_shows_grants(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw", role=SystemUserRole.ADMIN))
    asyncio.run(seed_user(storage, username="bob", password="bobpw", role=SystemUserRole.ANALYST))

    async def _grant() -> None:
        admin = await storage.get_system_user_by_username("admin")
        bob = await storage.get_system_user_by_username("bob")
        assert admin is not None and bob is not None
        await storage.grant_scope(
            user_id=bob.id,
            scope="read:metrics",
            granted_at=datetime.now(tz=UTC),
            granted_by_user_id=admin.id,
        )

    asyncio.run(_grant())
    # No --as, no password input — list is read-only and ungated.
    result = runner.invoke(app, ["user", "scopes", "list", "bob", "--data-dir", str(data_dir)])
    assert result.exit_code == 0, result.output
    assert "role=analyst" in result.output
    assert "read:metrics" in result.output


def test_scopes_revoke_removes_grant(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw", role=SystemUserRole.ADMIN))
    asyncio.run(seed_user(storage, username="bob", password="bobpw", role=SystemUserRole.VIEWER))

    async def _grant() -> object:
        admin = await storage.get_system_user_by_username("admin")
        bob = await storage.get_system_user_by_username("bob")
        assert admin is not None and bob is not None
        await storage.grant_scope(
            user_id=bob.id,
            scope="read:metrics",
            granted_at=datetime.now(tz=UTC),
            granted_by_user_id=admin.id,
        )
        return bob.id

    bob_id = asyncio.run(_grant())
    result = runner.invoke(
        app,
        [
            "user",
            "scopes",
            "revoke",
            "bob",
            "read:metrics",
            "--as",
            "admin",
            "--data-dir",
            str(data_dir),
        ],
        input="adminpw\n",
    )
    assert result.exit_code == 0, result.output

    async def _after() -> list[str]:
        return [r.scope for r in await storage.list_explicit_scopes(bob_id)]

    assert asyncio.run(_after()) == []


def test_grant_unknown_authorizer_exits_3(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    # A user exists (so this is the gated path), but --as names no one.
    asyncio.run(seed_user(storage, username="bob", password="bobpw", role=SystemUserRole.VIEWER))
    result = runner.invoke(
        app,
        [
            "user",
            "scopes",
            "grant",
            "bob",
            "read:metrics",
            "--as",
            "ghost",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert result.exit_code == 3, result.output
    assert "authorization failed" in result.output


def test_grant_corrupt_mfa_key_exits_3(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    seed = generate_secret()
    asyncio.run(
        seed_user(
            storage,
            username="admin",
            password="adminpw",
            role=SystemUserRole.ADMIN,
            mfa_seed=seed,
        )
    )
    asyncio.run(seed_user(storage, username="bob", password="bobpw", role=SystemUserRole.VIEWER))
    # Rewrite the MFA key so the stored secret can no longer be decrypted —
    # the gate must fail closed (exit 3), not raise a traceback.
    (data_dir / "jwt" / "mfa_key").write_bytes(Fernet.generate_key())
    result = runner.invoke(
        app,
        [
            "user",
            "scopes",
            "grant",
            "bob",
            "read:metrics",
            "--as",
            "admin",
            "--data-dir",
            str(data_dir),
        ],
        input="adminpw\n123456\n",
    )
    assert result.exit_code == 3, result.output


def test_revoke_nonexistent_grant_reports_none(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw", role=SystemUserRole.ADMIN))
    asyncio.run(seed_user(storage, username="bob", password="bobpw", role=SystemUserRole.VIEWER))
    result = runner.invoke(
        app,
        [
            "user",
            "scopes",
            "revoke",
            "bob",
            "read:metrics",
            "--as",
            "admin",
            "--data-dir",
            str(data_dir),
        ],
        input="adminpw\n",
    )
    assert result.exit_code == 0, result.output
    assert "was not an explicit grant" in result.output
    assert "(none)" in result.output


def test_scopes_list_no_explicit_grants(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="bob", password="bobpw", role=SystemUserRole.VIEWER))
    result = runner.invoke(app, ["user", "scopes", "list", "bob", "--data-dir", str(data_dir)])
    assert result.exit_code == 0, result.output
    assert "explicit grants: (none)" in result.output


def test_scopes_list_unknown_user_exits_2(storage: BaseRepository, data_dir: Path) -> None:
    result = runner.invoke(app, ["user", "scopes", "list", "ghost", "--data-dir", str(data_dir)])
    assert result.exit_code == 2, result.output
    assert "unknown user" in result.output


def test_grant_unknown_target_exits_2(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw", role=SystemUserRole.ADMIN))
    result = runner.invoke(
        app,
        [
            "user",
            "scopes",
            "grant",
            "ghost",
            "read:metrics",
            "--as",
            "admin",
            "--data-dir",
            str(data_dir),
        ],
        input="adminpw\n",
    )
    assert result.exit_code == 2, result.output
    assert "unknown user" in result.output


def test_revoke_unknown_target_exits_2(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw", role=SystemUserRole.ADMIN))
    result = runner.invoke(
        app,
        [
            "user",
            "scopes",
            "revoke",
            "ghost",
            "read:metrics",
            "--as",
            "admin",
            "--data-dir",
            str(data_dir),
        ],
        input="adminpw\n",
    )
    assert result.exit_code == 2, result.output
    assert "unknown user" in result.output


def test_authorizer_without_credential_exits_3(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    # A profile row with no credential cannot authenticate — fail closed.
    asyncio.run(
        seed_user(
            storage,
            username="hollow",
            password="x",
            role=SystemUserRole.ADMIN,
            with_credential=False,
        )
    )
    asyncio.run(seed_user(storage, username="bob", password="bobpw", role=SystemUserRole.VIEWER))
    result = runner.invoke(
        app,
        [
            "user",
            "scopes",
            "grant",
            "bob",
            "read:metrics",
            "--as",
            "hollow",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert result.exit_code == 3, result.output
    assert "authorization failed" in result.output
