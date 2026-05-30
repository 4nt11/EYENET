# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for ``eyenet user create`` (M9.A6).

Covers the bootstrap exception (empty table → ungated, forced admin), the
authorizer gate once a user exists, and the failure exit codes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from typer.testing import CliRunner

from eyenet.api.auth import verify_password
from eyenet.cli.main import app
from eyenet.contracts.enums import SystemUserRole
from eyenet.storage.repository import BaseRepository
from tests.unit.cli.conftest import SeedUser

runner = CliRunner()
pytestmark = pytest.mark.unit


def _generated_password(output: str) -> str:
    line = next(line for line in output.splitlines() if line.startswith("generated password"))
    return line.split(": ", 1)[1].strip()


def test_bootstrap_create_first_admin_ungated(storage: BaseRepository, data_dir: Path) -> None:
    result = runner.invoke(
        app,
        ["user", "create", "root", "--role", "admin", "--generate", "--data-dir", str(data_dir)],
    )
    assert result.exit_code == 0, result.output
    assert "created user 'root' (admin)" in result.output
    password = _generated_password(result.output)

    async def _check() -> SystemUserRole:
        user = await storage.get_system_user_by_username("root")
        assert user is not None
        cred = await storage.get_credential(user.id)
        assert cred is not None
        assert verify_password(password, cred.password_hash)
        return user.role

    assert asyncio.run(_check()) is SystemUserRole.ADMIN


def test_bootstrap_non_admin_first_user_rejected(storage: BaseRepository, data_dir: Path) -> None:
    result = runner.invoke(
        app,
        ["user", "create", "root", "--role", "viewer", "--generate", "--data-dir", str(data_dir)],
    )
    assert result.exit_code == 2, result.output
    assert "must be created with --role admin" in result.output


def test_duplicate_username_rejected(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="root", password="rootpw"))
    result = runner.invoke(
        app, ["user", "create", "root", "--generate", "--data-dir", str(data_dir)]
    )
    assert result.exit_code == 2, result.output
    assert "already exists" in result.output


def test_create_second_user_via_gate(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw", role=SystemUserRole.ADMIN))
    result = runner.invoke(
        app,
        [
            "user",
            "create",
            "bob",
            "--role",
            "analyst",
            "--as",
            "admin",
            "--generate",
            "--data-dir",
            str(data_dir),
        ],
        input="adminpw\n",
    )
    assert result.exit_code == 0, result.output
    assert "created user 'bob' (analyst)" in result.output
    # The seeded admin has no MFA — the gate warns and proceeds on password.
    assert "no MFA enrolled" in result.output

    async def _role() -> SystemUserRole:
        user = await storage.get_system_user_by_username("bob")
        assert user is not None
        return user.role

    assert asyncio.run(_role()) is SystemUserRole.ANALYST


def test_create_bad_authorizer_password_exits_3(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw", role=SystemUserRole.ADMIN))
    result = runner.invoke(
        app,
        ["user", "create", "bob", "--as", "admin", "--generate", "--data-dir", str(data_dir)],
        input="wrongpw\n",
    )
    assert result.exit_code == 3, result.output
    assert "authorization failed" in result.output


def test_create_missing_as_when_users_exist_exits_2(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw"))
    result = runner.invoke(
        app, ["user", "create", "bob", "--generate", "--data-dir", str(data_dir)]
    )
    assert result.exit_code == 2, result.output
    assert "--as" in result.output


def test_create_authorizer_insufficient_scope_exits_4(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="ana", password="anapw", role=SystemUserRole.ANALYST))
    result = runner.invoke(
        app,
        ["user", "create", "bob", "--as", "ana", "--generate", "--data-dir", str(data_dir)],
        input="anapw\n",
    )
    assert result.exit_code == 4, result.output
    assert "lacks 'admin:users'" in result.output


def test_bootstrap_create_with_password_prompt(storage: BaseRepository, data_dir: Path) -> None:
    # No --generate: the hidden confirmation prompt supplies the password.
    # --display-name / --email exercise the non-default profile fields.
    result = runner.invoke(
        app,
        [
            "user",
            "create",
            "root",
            "--role",
            "admin",
            "--display-name",
            "Root Operator",
            "--email",
            "root@example.com",
            "--data-dir",
            str(data_dir),
        ],
        input="s3cret-pw\ns3cret-pw\n",
    )
    assert result.exit_code == 0, result.output
    assert "created user 'root' (admin)" in result.output

    async def _check() -> None:
        user = await storage.get_system_user_by_username("root")
        assert user is not None
        assert user.display_name == "Root Operator"
        assert user.email == "root@example.com"
        cred = await storage.get_credential(user.id)
        assert cred is not None
        assert verify_password("s3cret-pw", cred.password_hash)

    asyncio.run(_check())
