"""Verifier unit-test fixtures.

Reset structlog before each test so `structlog.testing.capture_logs()`
intercepts events. Without this, an earlier test that triggered
``configure_logging`` leaves ``cache_logger_on_first_use=True`` active —
the module-level `_log` in ``eyenet/verifier/service.py`` then bypasses
the capture context and assertions on captured events fail.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import structlog


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    structlog.reset_defaults()
    yield
    structlog.reset_defaults()
