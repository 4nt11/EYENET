"""CLI integration: `eyenet linkage confirm/reject/suspect` write the right rows.

Drives the real CLI via typer.testing.CliRunner against a temp data_dir +
in-process MemoryBus. Asserts the LinkageRow transitions to the expected
state AND that the FeedbackPair side-effect fires only on confirm/reject.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from eyenet.cli.main import app
from eyenet.contracts.enums import LinkageState
from eyenet.storage import SQLiteStorage


def _seed_proposed_linkage(data_dir: Path) -> str:
    """Seed one PROPOSED Linkage row in a fresh data_dir; return its linkage_id."""

    async def _run() -> str:
        storage = SQLiteStorage(data_dir)
        a, b = sorted([uuid4(), uuid4()])
        try:
            row = await storage.insert_proposed_linkage(
                a, b, "test_method", 0.6, {"language": "es"}
            )
            return str(row.id)
        finally:
            await storage.close()

    return asyncio.run(_run())


def _assert_state_and_feedback(
    data_dir: Path,
    linkage_id: str,
    expected_state: LinkageState,
    expected_ground_truth: str | None,
) -> None:
    async def _run() -> None:
        from uuid import UUID

        storage = SQLiteStorage(data_dir)
        try:
            lid = UUID(linkage_id)
            row = await storage.get_linkage(lid)
            assert row is not None
            assert row.state == expected_state
            feedback = await storage.get_feedback_pair(lid)
            if expected_ground_truth is None:
                assert feedback is None
            else:
                assert feedback is not None
                assert feedback.ground_truth == expected_ground_truth
                # Sorted-pair invariant carried into the FeedbackPair row
                assert feedback.actor_a_id < feedback.actor_b_id
                assert isinstance(feedback.decided_at, datetime)
                assert feedback.decided_at.tzinfo is not None
        finally:
            await storage.close()

    asyncio.run(_run())


@pytest.fixture
def tmp_data_dir() -> Path:
    return Path(tempfile.mkdtemp())


@pytest.mark.integration
def test_linkage_confirm_writes_same_feedback(tmp_data_dir: Path) -> None:
    linkage_id = _seed_proposed_linkage(tmp_data_dir)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "linkage",
            "confirm",
            linkage_id,
            "--by",
            "op-test",
            "--memory-bus",
            "--data-dir",
            str(tmp_data_dir),
        ],
    )
    assert result.exit_code == 0, result.stdout
    _assert_state_and_feedback(
        tmp_data_dir,
        linkage_id,
        expected_state=LinkageState.CONFIRMED,
        expected_ground_truth="same",
    )


@pytest.mark.integration
def test_linkage_reject_writes_diff_feedback(tmp_data_dir: Path) -> None:
    linkage_id = _seed_proposed_linkage(tmp_data_dir)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "linkage",
            "reject",
            linkage_id,
            "--by",
            "op-test",
            "--notes",
            "different authors based on dialect",
            "--memory-bus",
            "--data-dir",
            str(tmp_data_dir),
        ],
    )
    assert result.exit_code == 0, result.stdout
    _assert_state_and_feedback(
        tmp_data_dir,
        linkage_id,
        expected_state=LinkageState.REJECTED,
        expected_ground_truth="diff",
    )


@pytest.mark.integration
def test_linkage_suspect_writes_no_feedback(tmp_data_dir: Path) -> None:
    """`suspect` is operator triage — still ambiguous, no ground truth."""
    linkage_id = _seed_proposed_linkage(tmp_data_dir)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "linkage",
            "suspect",
            linkage_id,
            "--by",
            "op-test",
            "--memory-bus",
            "--data-dir",
            str(tmp_data_dir),
        ],
    )
    assert result.exit_code == 0, result.stdout
    _assert_state_and_feedback(
        tmp_data_dir,
        linkage_id,
        expected_state=LinkageState.SUSPECTED,
        expected_ground_truth=None,
    )


@pytest.mark.integration
def test_linkage_confirm_then_overwrite_via_subsequent_reject_is_blocked(
    tmp_data_dir: Path,
) -> None:
    """Once CONFIRMED, the state machine refuses further transitions.

    The FeedbackPair row from the confirm stays; no reject row is written.
    """
    linkage_id = _seed_proposed_linkage(tmp_data_dir)
    runner = CliRunner()
    confirm_result = runner.invoke(
        app,
        [
            "linkage",
            "confirm",
            linkage_id,
            "--by",
            "op-test",
            "--memory-bus",
            "--data-dir",
            str(tmp_data_dir),
        ],
    )
    assert confirm_result.exit_code == 0

    # CONFIRMED is terminal — subsequent reject must fail.
    reject_result = runner.invoke(
        app,
        [
            "linkage",
            "reject",
            linkage_id,
            "--by",
            "op-test",
            "--memory-bus",
            "--data-dir",
            str(tmp_data_dir),
        ],
    )
    assert reject_result.exit_code != 0

    # Original CONFIRMED + "same" feedback survives.
    _assert_state_and_feedback(
        tmp_data_dir,
        linkage_id,
        expected_state=LinkageState.CONFIRMED,
        expected_ground_truth="same",
    )
