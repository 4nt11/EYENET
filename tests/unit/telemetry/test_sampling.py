"""PLAN §8.6 — should_keep_trace hook returns True by default."""

from __future__ import annotations

import pytest

from eyenet.telemetry.sampling import should_keep_trace


@pytest.mark.unit
def test_default_keeps_everything() -> None:
    assert should_keep_trace(object(), []) is True  # type: ignore[arg-type]
