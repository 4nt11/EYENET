"""Bus envelopes round-trip through JSON without drift."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts._base import TraceContext
from eyenet.contracts.attribution import (
    LinkageProposedEnvelope,
    ProfileCandidateEnvelope,
    ProfileCurrentEnvelope,
)
from eyenet.contracts.audit import AuditEvent
from eyenet.contracts.enums import EngagementScope, EngagementSubjectKind, SourceKind
from eyenet.contracts.identity import (
    EngagementAuthorizationEnvelope,
    IdentityLabelEnvelope,
)
from eyenet.contracts.raw_message import RawMessageEnvelope

TC = TraceContext(traceparent="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")
NOW = datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)
A = UUID("00000000-0000-0000-0000-000000000001")
B = UUID("00000000-0000-0000-0000-000000000002")


def _round_trip(model: object) -> None:
    cls = type(model)
    blob = model.model_dump_json()  # type: ignore[attr-defined]
    revived = cls.model_validate_json(blob)  # type: ignore[attr-defined]
    assert revived == model


@pytest.mark.contract
def test_raw_message_round_trip() -> None:
    env = RawMessageEnvelope(
        source=SourceKind.TELEGRAM,
        instance_id="abcd1234",
        evidence_ref="telegram:-100:42",
        actor_key="actor:" + "a" * 64,
        platform_groupid="-100",
        platform_msgid="42",
        sent_at_source=NOW,
        collected_at=NOW,
        length_chars=10,
        length_words=2,
        body_sha256="b" * 64,
        trace_context=TC,
    )
    _round_trip(env)


@pytest.mark.contract
def test_profile_candidate_round_trip() -> None:
    env = ProfileCandidateEnvelope(
        profile_id=A,
        actor_id=B,
        version=1,
        role_signal="lurker_or_observer",
        role_confidence=0.42,
        derived_at=NOW,
        derived_from_observation_count=10,
        trace_context=TC,
    )
    _round_trip(env)


@pytest.mark.contract
def test_profile_current_round_trip() -> None:
    env = ProfileCurrentEnvelope(
        profile_id=A,
        actor_id=B,
        version=1,
        role_signal=None,
        role_confidence=0.0,
        derived_at=NOW,
        derived_from_observation_count=0,
        trace_context=TC,
    )
    _round_trip(env)


@pytest.mark.contract
def test_linkage_proposed_round_trip() -> None:
    env = LinkageProposedEnvelope.from_pair(
        B,
        A,
        linkage_id=UUID("00000000-0000-0000-0000-000000000099"),
        method="manual",
        score=0.7,
        evidence={"distance": 12},
        proposed_at=NOW,
        trace_context=TC,
    )
    _round_trip(env)


@pytest.mark.contract
def test_identity_label_round_trip() -> None:
    from eyenet.contracts.enums import ConfidenceTier

    env = IdentityLabelEnvelope(
        label_id=UUID("00000000-0000-0000-0000-0000000000aa"),
        actor_id=A,
        label="credential_broker",
        confidence=ConfidenceTier.HIGH,
        applied_by="system_user_1",
        applied_at=NOW,
        rationale="rutify-Q2 confirmed",
        trace_context=TC,
    )
    _round_trip(env)


@pytest.mark.contract
def test_engagement_round_trip() -> None:
    env = EngagementAuthorizationEnvelope(
        auth_id=UUID("00000000-0000-0000-0000-0000000000bb"),
        subject_kind=EngagementSubjectKind.ACTOR,
        actor_id=A,
        authorized_by="system_user_1",
        authorized_at=NOW,
        scope=EngagementScope.OBSERVE_ONLY,
        trace_context=TC,
    )
    _round_trip(env)


@pytest.mark.contract
def test_audit_event_round_trip() -> None:
    env = AuditEvent(
        audit_id=UUID("00000000-0000-0000-0000-0000000000cc"),
        event="evidence_access",
        service="engine",
        instance_id="eng_1",
        subject_kind="actor",
        subject_id=A,
        evidence_ref="telegram:-100:42",
        payload={"reason": "test"},
        at=NOW,
        trace_context=TC,
    )
    _round_trip(env)
