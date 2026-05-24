"""Fixtures for the api-tier unit suite.

Mirrors the style of `tests/unit/contracts/conftest.py` — UTC-pinned
datetimes and a UUID factory so tests are deterministic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def uid() -> UUID:
    return UUID("01906f00-0000-7000-8000-000000000001")


@pytest.fixture
def uid2() -> UUID:
    return UUID("01906f00-0000-7000-8000-000000000002")


@pytest.fixture
def trace_id() -> str:
    return "0af7651916cd43dd8448eb211c80319c"  # pragma: allowlist secret


@pytest.fixture
def span_id() -> str:
    return "b7ad6b7169203331"  # pragma: allowlist secret
