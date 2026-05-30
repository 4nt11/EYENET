# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for ``eyenet user reset-password`` (M9.A6).

The load-bearing invariant: a password reset must NOT disturb the target's
MFA enrollment.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from typer.testing import CliRunner

from eyenet.api.auth import generate_secret, verify_password
from eyenet.cli.main import app
from eyenet.contracts.enums import SystemUserRole
from eyenet.storage.repository import BaseRepository
from tests.unit.cli.conftest import SeedUser

runner = CliRunner()
pytestmark = pytest.mark.unit


def test_reset_password_preserves_mfa(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw", role=SystemUserRole.ADMIN))
    asyncio.run(
        seed_user(
            storage,
            username="bob",
            password="oldpw",
            role=SystemUserRole.ANALYST,
            mfa_seed=generate_secret(),
        )
    )

    async def _before() -> tuple[str | None, str]:
        user = await storage.get_system_user_by_username("bob")
        assert user is not None
        cred = await storage.get_credential(user.id)
        assert cred is not None
        return cred.mfa_secret_encrypted, cred.password_hash

    enc_before, hash_before = asyncio.run(_before())
    assert enc_before is not None

    result = runner.invoke(
        app,
        [
            "user",
            "reset-password",
            "bob",
            "--as",
            "admin",
            "--generate",
            "--data-dir",
            str(data_dir),
        ],
        input="adminpw\n",
    )
    assert result.exit_code == 0, result.output
    line = next(
        line for line in result.output.splitlines() if line.startswith("generated password")
    )
    new_password = line.split(": ", 1)[1].strip()

    async def _after() -> tuple[str | None, str]:
        user = await storage.get_system_user_by_username("bob")
        assert user is not None
        cred = await storage.get_credential(user.id)
        assert cred is not None
        return cred.mfa_secret_encrypted, cred.password_hash

    enc_after, hash_after = asyncio.run(_after())
    assert enc_after == enc_before  # MFA enrollment untouched
    assert hash_after != hash_before  # password changed
    assert verify_password(new_password, hash_after)


def test_reset_password_unknown_target_exits_2(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw"))
    result = runner.invoke(
        app,
        [
            "user",
            "reset-password",
            "ghost",
            "--as",
            "admin",
            "--generate",
            "--data-dir",
            str(data_dir),
        ],
        input="adminpw\n",
    )
    assert result.exit_code == 2, result.output
    assert "unknown user" in result.output


def test_reset_password_bad_authorizer_exits_3(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw"))
    asyncio.run(seed_user(storage, username="bob", password="oldpw", role=SystemUserRole.VIEWER))
    result = runner.invoke(
        app,
        [
            "user",
            "reset-password",
            "bob",
            "--as",
            "admin",
            "--generate",
            "--data-dir",
            str(data_dir),
        ],
        input="nope\n",
    )
    assert result.exit_code == 3, result.output


def test_reset_password_insufficient_scope_exits_4(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="ana", password="anapw", role=SystemUserRole.ANALYST))
    asyncio.run(seed_user(storage, username="bob", password="oldpw", role=SystemUserRole.VIEWER))
    result = runner.invoke(
        app,
        ["user", "reset-password", "bob", "--as", "ana", "--generate", "--data-dir", str(data_dir)],
        input="anapw\n",
    )
    assert result.exit_code == 4, result.output
    assert "lacks 'admin:users'" in result.output


def test_reset_password_with_confirmation_prompt(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw", role=SystemUserRole.ADMIN))
    asyncio.run(seed_user(storage, username="bob", password="oldpw", role=SystemUserRole.VIEWER))
    # authorizer password, then the new password twice (confirmation prompt).
    result = runner.invoke(
        app,
        ["user", "reset-password", "bob", "--as", "admin", "--data-dir", str(data_dir)],
        input="adminpw\nbrandnew\nbrandnew\n",
    )
    assert result.exit_code == 0, result.output

    async def _check() -> None:
        user = await storage.get_system_user_by_username("bob")
        assert user is not None
        cred = await storage.get_credential(user.id)
        assert cred is not None
        assert verify_password("brandnew", cred.password_hash)

    asyncio.run(_check())


def test_reset_password_target_without_credential_exits_2(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw", role=SystemUserRole.ADMIN))
    asyncio.run(
        seed_user(
            storage, username="bob", password="x", role=SystemUserRole.VIEWER, with_credential=False
        )
    )
    result = runner.invoke(
        app,
        [
            "user",
            "reset-password",
            "bob",
            "--as",
            "admin",
            "--generate",
            "--data-dir",
            str(data_dir),
        ],
        input="adminpw\n",
    )
    assert result.exit_code == 2, result.output
    assert "no credential row" in result.output
