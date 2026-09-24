# SPDX-License-Identifier: AGPL-3.0-or-later
"""actor_primary_handle: @handle > display name > raw platform id."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.api.v1.schemas.actors import actor_primary_handle
from eyenet.models.actor import ActorTable


def _actor(*, handle: str | None, display: str | None, uid: str) -> ActorTable:
    now = datetime.now(tz=UTC)
    return ActorTable(
        id=uuid4(),
        actor_key=f"actor:tg:{uid}",
        source_id=uuid4(),
        platform_userid=uid,
        current_handle=handle,
        current_display_name=display,
        first_seen_at_source=now,
        first_seen_at_ingest=now,
        last_seen_at_source=now,
        last_seen_at_ingest=now,
    )


@pytest.mark.unit
def test_prefers_handle() -> None:
    a = _actor(handle="@boss", display="Nicole Lee", uid="8595058147")
    assert actor_primary_handle(a) == "@boss"


@pytest.mark.unit
def test_falls_back_to_display_name_not_raw_id() -> None:
    a = _actor(handle=None, display="Nicole Lee", uid="8595058147")
    assert actor_primary_handle(a) == "Nicole Lee"


@pytest.mark.unit
def test_last_resort_is_platform_id() -> None:
    a = _actor(handle=None, display=None, uid="8595058147")
    assert actor_primary_handle(a) == "8595058147"
