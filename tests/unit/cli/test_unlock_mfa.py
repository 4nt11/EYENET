"""Unit tests for ``eyenet user unlock-mfa`` (M9.A3)."""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from typer.testing import CliRunner

from eyenet.cli.main import app
from eyenet.contracts.enums import SystemUserRole
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

runner = CliRunner()


@pytest.fixture
def data_dir() -> Path:
    return Path(tempfile.mkdtemp())


@pytest.fixture
def storage(data_dir: Path) -> BaseRepository:
    return get_repository(data_dir=data_dir)


@pytest.mark.unit
def test_unlock_mfa_inside_active_window(
    storage: BaseRepository,
    data_dir: Path,
) -> None:
    user_id = UUID("22222222-2222-7222-8222-222222222222")
    now = datetime.now(tz=UTC)

    async def _seed() -> None:
        await storage.put_system_user(
            user_id=user_id,
            username="ada",
            display_name="ada",
            role=SystemUserRole.ANALYST,
            created_at=now,
        )
        for _ in range(5):
            chall = await storage.create_mfa_challenge(
                user_id=user_id,
                issued_at=now,
                expires_at=now + timedelta(seconds=90),
            )
            await storage.bump_mfa_challenge_failures(chall.challenge_id)

    asyncio.run(_seed())

    result = runner.invoke(app, ["user", "unlock-mfa", "ada", "--data-dir", str(data_dir)])
    assert result.exit_code == 0
    assert "cleared 5 failed-challenge row(s)" in result.output

    async def _failures_after() -> int:
        return await storage.count_recent_mfa_failures(
            user_id=user_id,
            since=now - timedelta(minutes=15),
        )

    assert asyncio.run(_failures_after()) == 0


@pytest.mark.unit
def test_unlock_mfa_unknown_user_exits_nonzero(data_dir: Path) -> None:
    result = runner.invoke(app, ["user", "unlock-mfa", "ghost", "--data-dir", str(data_dir)])
    assert result.exit_code == 2
    assert "unknown user" in result.output
