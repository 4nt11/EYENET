"""Shared fixtures for contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyenet.contracts._base import TraceContext


@pytest.fixture
def trace() -> TraceContext:
    return TraceContext(
        traceparent="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        tracestate=None,
    )


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)
