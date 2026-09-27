# SPDX-License-Identifier: AGPL-3.0-or-later
"""PUT /v1/incidents/{message_id}/labels handler — direct-call (ASGI not coverage-traced)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eyenet.api.deps import UnprocessableError
from eyenet.api.v1.incidents.api_set_incident_label import set_incident_label
from eyenet.api.v1.schemas.incidents import IncidentLabelUpdate
from eyenet.contracts.incident import IncidentLabelRow

pytestmark = pytest.mark.unit


class _FakeStorage:
    def __init__(self) -> None:
        self.saved: dict = {}

    async def set_incident_label(self, message_id, labels, *, decided_by, reason, decided_at):
        row = IncidentLabelRow(
            message_id=message_id, labels=labels, reason=reason,
            decided_by=decided_by, decided_at=decided_at,
        )
        self.saved[message_id] = row
        return row


class _FakeAudit:
    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, **kw):
        self.events.append(kw)


def _user():
    return SimpleNamespace(user_id=uuid4(), username="op.anti")


def test_relabel_stores_dedups_and_audits() -> None:
    storage, audit = _FakeStorage(), _FakeAudit()
    mid = uuid4()
    out = asyncio.run(
        set_incident_label(
            message_id=mid,
            body=IncidentLabelUpdate(labels=["leak", "leak", "incident"], reason="misfire"),
            current_user=_user(), storage=storage, audit=audit,
        )
    )
    assert out.labels == ["leak", "incident"]  # deduped, order preserved
    assert out.decided_by == "op.anti"
    assert audit.events[0]["event"] == "eyenet.audit.incident.relabeled"
    assert audit.events[0]["subject_id"] == mid


def test_relabel_empty_is_false_positive() -> None:
    storage, audit = _FakeStorage(), _FakeAudit()
    out = asyncio.run(
        set_incident_label(
            message_id=uuid4(), body=IncidentLabelUpdate(labels=[], reason="not a leak"),
            current_user=_user(), storage=storage, audit=audit,
        )
    )
    assert out.labels == []  # empty = false positive, a valid correction


def test_relabel_rejects_unknown_label() -> None:
    storage, audit = _FakeStorage(), _FakeAudit()
    with pytest.raises(UnprocessableError):
        asyncio.run(
            set_incident_label(
                message_id=uuid4(),
                body=IncidentLabelUpdate(labels=["banana"], reason=None),
                current_user=_user(), storage=storage, audit=audit,
            )
        )
