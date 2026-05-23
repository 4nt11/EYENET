"""PLAN §9.3 / MODELS §2.14 — audit log is hash-chained.

Insertion / deletion / edit breaks the chain on a single forward walk.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts.audit import (
    GENESIS_PREV_HASH,
    AuditLogRow,
    compute_self_hash,
    verify_chain,
)


def _row(idx: int, prev_hash: str) -> AuditLogRow:
    row = AuditLogRow(
        id=UUID(f"00000000-0000-0000-0000-{idx:012d}"),
        event="evidence_access",
        service="engine",
        instance_id="eng_1",
        subject_kind="actor",
        at=datetime(2026, 5, 4, 12, idx % 60, 0, tzinfo=UTC),
        prev_hash=prev_hash,
        self_hash="0" * 64,  # placeholder, recomputed below
    )
    return row.model_copy(update={"self_hash": compute_self_hash(row)})


def _make_chain(n: int) -> list[AuditLogRow]:
    rows: list[AuditLogRow] = []
    prev = GENESIS_PREV_HASH
    for i in range(n):
        row = _row(i, prev)
        rows.append(row)
        prev = row.self_hash
    return rows


@pytest.mark.contract
def test_self_hash_deterministic() -> None:
    a = _row(1, GENESIS_PREV_HASH)
    b = _row(1, GENESIS_PREV_HASH)
    assert a.self_hash == b.self_hash


@pytest.mark.contract
def test_clean_chain_verifies() -> None:
    rows = _make_chain(5)
    ok, broken = verify_chain(rows)
    assert ok
    assert broken is None


@pytest.mark.contract
def test_edit_breaks_chain() -> None:
    rows = _make_chain(5)
    # Mutate row 2's payload — self_hash now mismatches.
    rows[2] = rows[2].model_copy(update={"event": "tampered"})
    ok, broken = verify_chain(rows)
    assert not ok
    assert broken == 2


@pytest.mark.contract
def test_deletion_breaks_chain() -> None:
    rows = _make_chain(5)
    del rows[2]
    ok, broken = verify_chain(rows)
    assert not ok
    assert broken == 2


@pytest.mark.contract
def test_insertion_breaks_chain() -> None:
    rows = _make_chain(5)
    intruder = _row(99, GENESIS_PREV_HASH)
    rows.insert(2, intruder)
    ok, broken = verify_chain(rows)
    assert not ok
    assert broken == 2
