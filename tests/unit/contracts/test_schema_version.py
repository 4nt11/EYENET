"""PLAN §4.1 — every BusEnvelope carries `schema_version`. Forward-minor compat."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts._base import SCHEMA_VERSION, TraceContext
from eyenet.contracts.attribution import ProfileCandidateEnvelope

TC = TraceContext(traceparent="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")
NOW = datetime(2026, 5, 4, tzinfo=UTC)
A = UUID("00000000-0000-0000-0000-000000000001")


@pytest.mark.contract
def test_default_includes_current_schema_version() -> None:
    env = ProfileCandidateEnvelope(
        profile_id=A,
        actor_id=A,
        version=1,
        role_confidence=0.0,
        derived_at=NOW,
        derived_from_observation_count=0,
        trace_context=TC,
    )
    assert env.schema_version == SCHEMA_VERSION


@pytest.mark.contract
def test_consumer_accepts_older_minor_version() -> None:
    env = ProfileCandidateEnvelope(
        profile_id=A,
        actor_id=A,
        version=1,
        role_confidence=0.0,
        derived_at=NOW,
        derived_from_observation_count=0,
        trace_context=TC,
    )
    blob = json.loads(env.model_dump_json())
    blob["schema_version"] = "1.0"  # an older minor on the same major
    revived = ProfileCandidateEnvelope.model_validate(blob)
    assert revived.schema_version == "1.0"
