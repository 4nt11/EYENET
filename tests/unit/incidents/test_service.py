# SPDX-License-Identifier: AGPL-3.0-or-later
"""IncidentClassifierService flush logic — isolated (fake storage/bus/audit, no model)."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from eyenet.incidents import service as svc
from eyenet.incidents.classifier import HeadScore
from eyenet.incidents.service import IncidentClassifierService

pytestmark = pytest.mark.unit


class _FakeStorage:
    def __init__(self, msgs: dict) -> None:
        self._msgs = msgs
        self.saved: list = []

    async def messages_by_evidence_refs(self, refs):
        return {r: self._msgs[r] for r in refs if r in self._msgs}

    async def attachment_files_by_message_ids(self, message_ids):
        return {}

    async def put_incidents_bulk(self, rows):
        self.saved.extend(rows)


class _FakeAudit:
    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, **kw):
        self.events.append(kw)


class _FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

    async def subscribe(self, *a, **k):  # pragma: no cover
        pass

    async def publish(self, subject, payload, headers=None):
        self.published.append((subject, payload))


def _service(storage) -> IncidentClassifierService:
    s = IncidentClassifierService(bus=_FakeBus(), storage=storage, batch_size=2)
    s._audit = _FakeAudit()  # bypass real AuditEmitter
    return s


def test_flush_stores_only_fired_and_audits(monkeypatch):
    mid1, mid2 = uuid4(), uuid4()
    storage = _FakeStorage({"ref1": (mid1, "selling ddos script"), "ref2": (mid2, "gm hello")})
    # fake model: "ddos" text fires tooling, everything else fires nothing
    monkeypatch.setattr(
        svc.classifier,
        "classify_batch",
        lambda texts: [
            [HeadScore("tooling", 0.9, "ddos" in t), HeadScore("leak", 0.05, False)] for t in texts
        ],
    )
    monkeypatch.setattr(svc.classifier, "prefilter_labels", lambda t: set())

    s = _service(storage)
    s._buffer = ["ref1", "ref2"]
    asyncio.run(s._flush())

    assert len(storage.saved) == 1  # only the fired message stored
    row = storage.saved[0]
    assert row.message_id == mid1
    assert row.labels == ["tooling"]
    assert row.scores == {"tooling": 0.9, "leak": 0.05}  # all heads scored
    assert len(s._audit.events) == 1  # one detection audited
    assert s._audit.events[0]["event"] == "incident_detected"
    # the fired incident is published on the bus for the triage feed
    assert len(s._bus.published) == 1
    subject, payload = s._bus.published[0]
    assert subject == "incident.detected"
    assert b"tooling" in payload


def test_flush_fuses_prefilter(monkeypatch):
    mid = uuid4()
    storage = _FakeStorage({"ref1": (mid, "fresh cloud logs pass: t.me/x")})
    # model fires nothing; prefilter catches infostealer -> cascade must store it
    monkeypatch.setattr(
        svc.classifier,
        "classify_batch",
        lambda texts: [[HeadScore("infostealer", 0.02, False)] for _ in texts],
    )
    monkeypatch.setattr(svc.classifier, "prefilter_labels", lambda t: {"infostealer"})

    s = _service(storage)
    s._buffer = ["ref1"]
    asyncio.run(s._flush())

    assert len(storage.saved) == 1
    assert storage.saved[0].labels == ["infostealer"]


def test_flush_dedups_and_empty_is_noop(monkeypatch):
    storage = _FakeStorage({})
    monkeypatch.setattr(svc.classifier, "classify_batch", lambda texts: [])
    monkeypatch.setattr(svc.classifier, "prefilter_labels", lambda t: set())
    s = _service(storage)
    s._buffer = ["gone", "gone"]  # dedups to 1; no message rows -> no save
    asyncio.run(s._flush())
    assert storage.saved == []
    asyncio.run(s._flush())  # empty buffer -> clean no-op
