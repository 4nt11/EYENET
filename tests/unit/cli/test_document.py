"""Unit tests for ``eyenet document ingest`` via Typer CliRunner.

The sandbox is unarmed in the unit process, so a real file ingests as
CLASSIFIED (§0 fail-closed) — which still exercises the full command wiring:
file read, storage construction, the ingest pipeline, audit emission, and the
output line. No nsjail or network involved.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from eyenet.cli.main import app

pytestmark = pytest.mark.unit

runner = CliRunner()


@pytest.fixture
def data_dir() -> Path:
    return Path(tempfile.mkdtemp())


def test_ingest_classifies_and_prints(data_dir: Path, tmp_path: Path) -> None:
    doc = tmp_path / "evidence.pdf"
    doc.write_bytes(b"%PDF-1.7 some bytes")
    result = runner.invoke(app, ["document", "ingest", str(doc), "--data-dir", str(data_dir)])
    assert result.exit_code == 0, result.output
    assert "tier=classified" in result.output  # unarmed sandbox → fail-closed
    assert "sha256=" in result.output
    assert "review=" in result.output


def test_ingest_missing_file_exits_nonzero(data_dir: Path) -> None:
    result = runner.invoke(
        app, ["document", "ingest", "/no/such/file.pdf", "--data-dir", str(data_dir)]
    )
    assert result.exit_code == 1
    assert "not a file" in result.output
