# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for ``eyenet user reset-mfa`` (M9.A6).

Distinct from ``unlock-mfa``: this wipes the encrypted TOTP secret entirely,
forcing re-enrollment.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from typer.testing import CliRunner

from eyenet.api.auth import generate_secret
from eyenet.cli.main import app
from eyenet.contracts.enums import SystemUserRole
from eyenet.storage.repository import BaseRepository
from tests.unit.cli.conftest import SeedUser

runner = CliRunner()
pytestmark = pytest.mark.unit


def test_reset_mfa_wipes_enrollment(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw", role=SystemUserRole.ADMIN))
    asyncio.run(
        seed_user(
            storage,
            username="bob",
            password="bobpw",
            role=SystemUserRole.ANALYST,
            mfa_seed=generate_secret(),
        )
    )

    async def _enrolled() -> tuple[object, str | None]:
        bob = await storage.get_system_user_by_username("bob")
        assert bob is not None
        cred = await storage.get_credential(bob.id)
        assert cred is not None
        return bob.id, cred.mfa_secret_encrypted

    bob_id, enc_before = asyncio.run(_enrolled())
    assert enc_before is not None

    result = runner.invoke(
        app,
        ["user", "reset-mfa", "bob", "--as", "admin", "--data-dir", str(data_dir)],
        input="adminpw\n",
    )
    assert result.exit_code == 0, result.output
    assert "enrollment wiped" in result.output

    async def _after() -> str | None:
        cred = await storage.get_credential(bob_id)
        assert cred is not None
        return cred.mfa_secret_encrypted

    assert asyncio.run(_after()) is None


def test_reset_mfa_unknown_target_exits_2(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw"))
    result = runner.invoke(
        app,
        ["user", "reset-mfa", "ghost", "--as", "admin", "--data-dir", str(data_dir)],
        input="adminpw\n",
    )
    assert result.exit_code == 2, result.output
    assert "unknown user" in result.output


def test_reset_mfa_bad_authorizer_exits_3(
    storage: BaseRepository, data_dir: Path, seed_user: SeedUser
) -> None:
    asyncio.run(seed_user(storage, username="admin", password="adminpw"))
    asyncio.run(seed_user(storage, username="bob", password="bobpw", role=SystemUserRole.VIEWER))
    result = runner.invoke(
        app,
        ["user", "reset-mfa", "bob", "--as", "admin", "--data-dir", str(data_dir)],
        input="wrong\n",
    )
    assert result.exit_code == 3, result.output


def test_reset_mfa_target_without_credential_exits_2(
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
        ["user", "reset-mfa", "bob", "--as", "admin", "--data-dir", str(data_dir)],
        input="adminpw\n",
    )
    assert result.exit_code == 2, result.output
    assert "no credential row" in result.output
