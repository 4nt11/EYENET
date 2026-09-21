# SPDX-License-Identifier: AGPL-3.0-or-later
"""sysstats.snapshot() — host self-report shape."""

from __future__ import annotations

from pathlib import Path

import pytest

from eyenet.telemetry import sysstats

pytestmark = pytest.mark.unit


def test_snapshot_shape(tmp_path: Path) -> None:
    snap = sysstats.snapshot(tmp_path)
    assert set(snap) == {"cpu_percent", "mem", "disk", "load1"}
    assert snap["cpu_percent"] >= 0.0
    assert set(snap["mem"]) == {"used", "total", "percent"}
    assert snap["mem"]["total"] > 0
    # disk block reflects the passed data volume + root, each with byte fields
    assert set(snap["disk"]) == {"data", "root"}
    for vol in snap["disk"].values():
        assert set(vol) == {"used", "free", "total"}
        assert vol["total"] > 0
    assert snap["load1"] >= 0.0
