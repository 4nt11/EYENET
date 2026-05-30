# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract: STREAM_TOPIC_SCOPE binds every topic to a real stream:* scope (M9.A5).

Guards the topic→scope map and the role baselines from silently drifting
apart — if someone adds a StreamTopic or renames a stream:* scope, one of
these fails instead of the mint gate quietly mis-authorizing.
"""

from __future__ import annotations

import pytest

from eyenet.api.auth import ROLE_BASELINE
from eyenet.api.v1.schemas.enums import StreamTopic
from eyenet.api.v1.stream import STREAM_TOPIC_SCOPE

pytestmark = pytest.mark.contract

_ALL_BASELINE_SCOPES = frozenset().union(*ROLE_BASELINE.values())


def test_every_topic_is_mapped() -> None:
    assert set(STREAM_TOPIC_SCOPE) == set(StreamTopic)


def test_every_mapped_scope_is_a_stream_scope() -> None:
    for scope in STREAM_TOPIC_SCOPE.values():
        assert scope.startswith("stream:"), scope


def test_every_mapped_scope_exists_in_some_baseline() -> None:
    # A topic mapped to a scope no role can ever hold would be unmintable —
    # a dead topic. Each must be grantable to at least one role (ADMIN holds
    # all four).
    for topic, scope in STREAM_TOPIC_SCOPE.items():
        assert scope in _ALL_BASELINE_SCOPES, (topic, scope)
