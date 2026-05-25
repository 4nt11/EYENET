"""Unit tests for the linkage CLI subcommands using Typer CliRunner."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from typer.testing import CliRunner

from eyenet.cli.main import app
from eyenet.contracts.attribution import LinkageRow
from eyenet.contracts.enums import LinkageState
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_ACTOR_A = UUID("00000000-0000-0000-0000-000000000001")
_ACTOR_B = UUID("00000000-0000-0000-0000-000000000002")

runner = CliRunner()


@pytest.fixture
def data_dir() -> Path:
    return Path(tempfile.mkdtemp())


@pytest.fixture
def storage(data_dir: Path) -> BaseRepository:
    return get_repository(data_dir=data_dir)


def _insert_proposed(storage: BaseRepository) -> UUID:
    async def _run() -> UUID:
        row = cast(
            "LinkageRow",
            await storage.insert_proposed_linkage(
                _ACTOR_A, _ACTOR_B, method="function_word_simhash_hamming", score=0.9, evidence={}
            ),
        )
        return row.id

    return asyncio.run(_run())


@pytest.mark.unit
def test_linkage_list_shows_row(data_dir: Path, storage: BaseRepository) -> None:
    _insert_proposed(storage)
    result = runner.invoke(app, ["linkage", "list", "--data-dir", str(data_dir)])
    assert result.exit_code == 0
    assert "function_word_simhash_hamming" in result.output or "proposed" in result.output


@pytest.mark.unit
def test_linkage_list_empty(data_dir: Path) -> None:
    result = runner.invoke(app, ["linkage", "list", "--data-dir", str(data_dir)])
    assert result.exit_code == 0
    assert "no linkages found" in result.output


@pytest.mark.unit
def test_linkage_list_filters_by_state(data_dir: Path, storage: BaseRepository) -> None:
    _insert_proposed(storage)
    result = runner.invoke(
        app, ["linkage", "list", "--data-dir", str(data_dir), "--state", "confirmed"]
    )
    assert result.exit_code == 0
    assert "no linkages found" in result.output


@pytest.mark.unit
def test_linkage_suspect_transitions_state(data_dir: Path, storage: BaseRepository) -> None:
    lid = _insert_proposed(storage)
    result = runner.invoke(
        app,
        [
            "linkage",
            "suspect",
            str(lid),
            "--by",
            "anti",
            "--memory-bus",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert result.exit_code == 0

    async def _check() -> LinkageState:
        row = await storage.get_linkage(lid)
        assert row is not None
        return cast("LinkageRow", row).state

    state = asyncio.run(_check())
    assert state == LinkageState.SUSPECTED


@pytest.mark.unit
def test_linkage_confirm_transitions_state(data_dir: Path, storage: BaseRepository) -> None:
    lid = _insert_proposed(storage)
    result = runner.invoke(
        app,
        [
            "linkage",
            "confirm",
            str(lid),
            "--by",
            "anti",
            "--memory-bus",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert result.exit_code == 0

    async def _check() -> LinkageState:
        row = await storage.get_linkage(lid)
        assert row is not None
        return cast("LinkageRow", row).state

    state = asyncio.run(_check())
    assert state == LinkageState.CONFIRMED


@pytest.mark.unit
def test_linkage_reject_transitions_state(data_dir: Path, storage: BaseRepository) -> None:
    lid = _insert_proposed(storage)
    result = runner.invoke(
        app,
        [
            "linkage",
            "reject",
            str(lid),
            "--by",
            "anti",
            "--memory-bus",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert result.exit_code == 0

    async def _check() -> LinkageState:
        row = await storage.get_linkage(lid)
        assert row is not None
        return cast("LinkageRow", row).state

    state = asyncio.run(_check())
    assert state == LinkageState.REJECTED


@pytest.mark.unit
def test_linkage_suspect_not_found(data_dir: Path) -> None:
    fake = UUID("00000000-0000-0000-0000-999999999999")
    result = runner.invoke(
        app,
        [
            "linkage",
            "suspect",
            str(fake),
            "--by",
            "anti",
            "--memory-bus",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert result.exit_code != 0


@pytest.mark.unit
def test_linkage_confirm_illegal_transition(data_dir: Path, storage: BaseRepository) -> None:
    lid = _insert_proposed(storage)

    async def _confirm() -> None:
        await storage.transition_linkage(lid, LinkageState.CONFIRMED, decided_by="anti")

    asyncio.run(_confirm())

    result = runner.invoke(
        app,
        [
            "linkage",
            "reject",
            str(lid),
            "--by",
            "anti",
            "--memory-bus",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert result.exit_code != 0
