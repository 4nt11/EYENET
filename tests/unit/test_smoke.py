"""Bootstrap smoke tests — verify the package imports and the CLI runs.

These exist so the v0 scaffold passes the coverage gate. Real tests
arrive with Milestone 0 (contracts).
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import eyenet
from eyenet.cli.main import app


@pytest.mark.unit
def test_package_version() -> None:
    assert eyenet.__version__ == "0.0.0"


@pytest.mark.unit
def test_cli_version_command() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "0.0.0" in result.stdout
