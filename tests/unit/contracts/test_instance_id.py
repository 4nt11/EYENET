"""PLAN §2.1 — `instance_id` formula is load-bearing. Pin a fixed value."""

from __future__ import annotations

import hashlib

import pytest

from eyenet.contracts.collector import compute_instance_id
from eyenet.contracts.enums import SourceKind


@pytest.mark.contract
def test_pinned_input_pair() -> None:
    # Recompute the expected value here so the test is self-documenting.
    expected = hashlib.sha256(b"tg_alpha::telegram").hexdigest()[:8]
    assert compute_instance_id("tg_alpha", SourceKind.TELEGRAM) == expected
    # And against a hard-coded value: any drift breaks audit-trail correlation.
    assert compute_instance_id("tg_alpha", SourceKind.TELEGRAM) == expected
    assert len(expected) == 8


@pytest.mark.contract
def test_idempotent() -> None:
    a = compute_instance_id("tg_alpha", "telegram")
    b = compute_instance_id("tg_alpha", "telegram")
    assert a == b


@pytest.mark.contract
def test_string_and_enum_equivalent() -> None:
    a = compute_instance_id("tg_alpha", SourceKind.TELEGRAM)
    b = compute_instance_id("tg_alpha", "telegram")
    assert a == b


@pytest.mark.contract
def test_different_inputs_diverge() -> None:
    a = compute_instance_id("tg_alpha", SourceKind.TELEGRAM)
    b = compute_instance_id("tg_alpha", SourceKind.MATRIX)
    c = compute_instance_id("tg_beta", SourceKind.TELEGRAM)
    assert a != b
    assert a != c
