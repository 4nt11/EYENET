"""NATS-style subject matching."""

from __future__ import annotations

import pytest

from eyenet.bus.subjects import is_valid_pattern, subject_matches


@pytest.mark.unit
@pytest.mark.parametrize(
    ("pattern", "subject", "expected"),
    [
        ("raw.message.telegram.abcd1234", "raw.message.telegram.abcd1234", True),
        ("raw.message.*.abcd1234", "raw.message.telegram.abcd1234", True),
        ("raw.message.>", "raw.message.telegram.abcd1234", True),
        ("raw.message.>", "raw.message", False),
        ("eyenet.audit.>", "eyenet.audit.engine", True),
        ("eyenet.audit.>", "eyenet.audit.engine.subspan", True),
        ("a.b.c", "a.b", False),
        ("a.b", "a.b.c", False),
        ("a.*.c", "a.b.c", True),
        ("a.*.c", "a.x.y.c", False),
    ],
)
def test_match(pattern: str, subject: str, expected: bool) -> None:
    assert subject_matches(pattern, subject) is expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("pattern", "ok"),
    [
        ("a.b.c", True),
        ("a.>", True),
        ("a.*", True),
        ("", False),
        ("a..b", False),
        ("a.>.b", False),
    ],
)
def test_is_valid_pattern(pattern: str, ok: bool) -> None:
    assert is_valid_pattern(pattern) is ok
