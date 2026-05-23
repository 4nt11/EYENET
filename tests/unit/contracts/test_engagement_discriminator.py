"""MODELS §2.13 — exactly-one-of (actor_id, group_id) per subject_kind."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from eyenet.contracts._base import TraceContext
from eyenet.contracts.enums import EngagementScope, EngagementSubjectKind
from eyenet.contracts.identity import (
    EngagementAuthorizationEnvelope,
    EngagementAuthorizationRow,
)

UID = UUID("00000000-0000-0000-0000-000000000001")
GID = UUID("00000000-0000-0000-0000-000000000002")
TC = TraceContext(traceparent="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")
NOW = datetime(2026, 5, 4, tzinfo=UTC)


def _envelope_kwargs() -> dict[str, Any]:
    return {
        "auth_id": UUID("00000000-0000-0000-0000-000000000099"),
        "authorized_by": "system_user_1",
        "authorized_at": NOW,
        "scope": EngagementScope.OBSERVE_ONLY,
        "trace_context": TC,
    }


@pytest.mark.contract
def test_actor_kind_requires_actor_id() -> None:
    EngagementAuthorizationEnvelope(
        subject_kind=EngagementSubjectKind.ACTOR,
        actor_id=UID,
        **_envelope_kwargs(),
    )
    with pytest.raises(ValueError, match="exactly one"):
        EngagementAuthorizationEnvelope(
            subject_kind=EngagementSubjectKind.ACTOR,
            **_envelope_kwargs(),
        )


@pytest.mark.contract
def test_group_kind_requires_group_id() -> None:
    EngagementAuthorizationEnvelope(
        subject_kind=EngagementSubjectKind.GROUP,
        group_id=GID,
        **_envelope_kwargs(),
    )
    with pytest.raises(ValueError, match="exactly one"):
        EngagementAuthorizationEnvelope(
            subject_kind=EngagementSubjectKind.GROUP,
            **_envelope_kwargs(),
        )


@pytest.mark.contract
def test_both_set_rejected() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        EngagementAuthorizationEnvelope(
            subject_kind=EngagementSubjectKind.ACTOR,
            actor_id=UID,
            group_id=GID,
            **_envelope_kwargs(),
        )


@pytest.mark.contract
def test_kind_mismatch_rejected() -> None:
    with pytest.raises(ValueError, match="requires actor_id"):
        EngagementAuthorizationEnvelope(
            subject_kind=EngagementSubjectKind.ACTOR,
            group_id=GID,  # wrong slot for kind
            **_envelope_kwargs(),
        )


@pytest.mark.contract
def test_row_validator_matches_envelope() -> None:
    EngagementAuthorizationRow(
        subject_kind=EngagementSubjectKind.GROUP,
        group_id=GID,
        authorized_by="system_user_1",
        authorized_at=NOW,
        scope=EngagementScope.OBSERVE_ONLY,
    )
    with pytest.raises(ValueError, match="exactly one"):
        EngagementAuthorizationRow(
            subject_kind=EngagementSubjectKind.GROUP,
            authorized_by="system_user_1",
            authorized_at=NOW,
            scope=EngagementScope.OBSERVE_ONLY,
        )
