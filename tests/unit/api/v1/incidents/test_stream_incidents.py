# SPDX-License-Identifier: AGPL-3.0-or-later
"""Incident SSE wiring — topic auth + mappings (no infinite-stream consumption)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from eyenet.api.deps import AuthError
from eyenet.api.streaming import require_topic
from eyenet.api.streaming.sse import TOPIC_SUBJECTS, _topic_of
from eyenet.api.v1.schemas.enums import StreamTopic
from eyenet.api.v1.stream._scopes import STREAM_TOPIC_SCOPE

pytestmark = pytest.mark.unit

_TOPIC = StreamTopic.INCIDENT.value


def test_topic_value_and_subject_mapping() -> None:
    assert _TOPIC == "incident.detected"
    assert TOPIC_SUBJECTS[_TOPIC] == ("incident.detected",)
    # routing label of the subject must equal the topic value
    assert _topic_of("incident.detected") == _TOPIC


def test_topic_scope_is_stream_incidents() -> None:
    assert STREAM_TOPIC_SCOPE[StreamTopic.INCIDENT] == "stream:incidents"


def test_require_topic_gate() -> None:
    ok = SimpleNamespace(topics=[_TOPIC])
    require_topic(ok, _TOPIC)  # no raise
    with pytest.raises(AuthError):
        require_topic(SimpleNamespace(topics=["attribution.linkage"]), _TOPIC)
