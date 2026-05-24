"""Shape tests for AuditRow / AuditVerifyResult + from_domain projection."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import AuditChainBreak, AuditRow, AuditVerifyResult
from eyenet.models.audit import AuditLogTable

pytestmark = pytest.mark.contract


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def uid() -> UUID:
    return UUID("01906f00-0000-7000-8000-000000000001")


@pytest.fixture
def uid2() -> UUID:
    return UUID("01906f00-0000-7000-8000-000000000002")


def test_audit_row_minimal(uid: UUID, now: datetime) -> None:
    row = AuditRow(
        event_id=uid,
        subject="evidence_access",
        ts=now,
        prev_hash="0" * 64,
        hash="1" * 64,
    )
    assert row.user_id is None
    assert row.payload == {}


def test_audit_row_trace_id_pattern(uid: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        AuditRow(
            event_id=uid,
            subject="x",
            ts=now,
            prev_hash="p",
            hash="h",
            trace_id="not-hex",
        )


def test_audit_row_span_id_pattern(uid: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        AuditRow(
            event_id=uid,
            subject="x",
            ts=now,
            prev_hash="p",
            hash="h",
            span_id="too-short",
        )


def test_audit_row_from_domain(uid: UUID, uid2: UUID, now: datetime) -> None:
    row = AuditLogTable(
        id=uid,
        event="evidence_access",
        service="api",
        instance_id="api-0",
        system_user_id=uid2,
        subject_kind="actor",
        subject_id=uid2,
        trace_id="0" * 32,
        span_id="0" * 16,
        payload={"request_id": "01HABC", "endpoint": "/v1/actors/x"},
        at=now,
        prev_hash="0" * 64,
        self_hash="1" * 64,
    )
    projected = AuditRow.from_domain(row)
    assert projected.event_id == uid
    assert projected.subject == "evidence_access"
    assert projected.user_id == uid2
    assert projected.ts == now
    assert projected.request_id == "01HABC"
    assert projected.hash == "1" * 64


def test_audit_row_from_domain_no_request_id(uid: UUID, now: datetime) -> None:
    row = AuditLogTable(
        id=uid,
        event="evidence_access",
        service="api",
        instance_id="api-0",
        subject_kind="actor",
        payload={},
        at=now,
        prev_hash="p",
        self_hash="h",
    )
    projected = AuditRow.from_domain(row)
    assert projected.request_id is None


def test_audit_verify_result_clean() -> None:
    result = AuditVerifyResult(verified=True, rows_checked=10)
    assert result.first_break is None


def test_audit_verify_result_with_break(uid: UUID) -> None:
    result = AuditVerifyResult(
        verified=False,
        rows_checked=5,
        first_break=AuditChainBreak(
            event_id=uid,
            expected_hash="a",
            actual_hash="b",
        ),
    )
    assert result.verified is False
    assert result.first_break is not None
    assert result.first_break.event_id == uid
