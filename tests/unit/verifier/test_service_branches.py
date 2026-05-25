"""Direct unit coverage for VerifierService branches that the integration
test (happy path) and the M8 E2E (live NATS) do not exercise:

- ``verifier.error``                         (exception inside .verify())
- ``verifier.no_qualified_results``          (all results skipped / 0 conf)
- ``verifier.skip_promotion_illegal_transition`` (state machine refuses)

We use ``MemoryBus`` + an in-memory SQLiteStorage + a stub Verifier
injected via the ``verifiers=`` constructor kwarg.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import structlog

from eyenet.bus import MemoryBus
from eyenet.contracts._base import TraceContext
from eyenet.contracts.attribution import (
    SUBJECT_LINKAGE_PROPOSED,
    LinkageProposedEnvelope,
)
from eyenet.contracts.enums import LinkageState
from eyenet.storage import SQLiteStorage
from eyenet.verifier.service import VerifierService
from eyenet.verifier.verifiers import VerificationResult

_TC = TraceContext(traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01")
_NOW = datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)
_A = UUID("00000000-0000-0000-0000-0000000000a1")
_B = UUID("00000000-0000-0000-0000-0000000000b2")


class _StubVerifier:
    """Minimal stub satisfying the Verifier Protocol."""

    name = "stub"
    version = "0"
    requires_language = False
    min_messages_per_actor = 0

    def __init__(
        self,
        *,
        raises: Exception | None = None,
        result: VerificationResult | None = None,
    ) -> None:
        self._raises = raises
        self._result = result

    def verify(
        self,
        corpus_a: list[str],
        corpus_b: list[str],
        *,
        language: str | None,
    ) -> VerificationResult:
        if self._raises is not None:
            raise self._raises
        assert self._result is not None
        return self._result


@pytest.fixture
def storage() -> SQLiteStorage:
    return SQLiteStorage(Path(tempfile.mkdtemp()))


def _envelope(linkage_id: UUID) -> LinkageProposedEnvelope:
    return LinkageProposedEnvelope(
        linkage_id=linkage_id,
        actor_a_id=_A,
        actor_b_id=_B,
        method="test",
        score=0.5,
        evidence={"language": "es"},
        proposed_at=_NOW,
        trace_context=_TC,
    )


def _events(caplog: list[Any]) -> list[str]:
    return [r["event"] for r in caplog]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verifier_error_branch_caught_and_logged(
    storage: SQLiteStorage,
) -> None:
    bus = MemoryBus()
    linkage = await storage.insert_proposed_linkage(_A, _B, method="test", score=0.5, evidence={})
    stub = _StubVerifier(raises=RuntimeError("boom"))
    service = VerifierService(bus=bus, storage=storage, verifiers=(stub,))
    await service.on_subscribe()

    with structlog.testing.capture_logs() as caplog:
        await bus.publish(
            SUBJECT_LINKAGE_PROPOSED,
            _envelope(linkage.id).model_dump_json().encode(),
        )
        await asyncio.sleep(0.1)

    events = _events(caplog)
    assert "verifier.error" in events
    err_log = next(r for r in caplog if r["event"] == "verifier.error")
    assert err_log["verifier"] == "stub"
    assert err_log["error"] == "boom"

    # No promotion — row stays PROPOSED.
    row = await storage.get_linkage(linkage.id)
    assert row is not None
    assert row.state == LinkageState.PROPOSED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_qualified_results_branch(storage: SQLiteStorage) -> None:
    bus = MemoryBus()
    linkage = await storage.insert_proposed_linkage(_A, _B, method="test", score=0.5, evidence={})
    skipped = VerificationResult(
        method="stub",
        score=0.0,
        confidence=0.0,
        skipped=True,
        skip_reason="corpus too short",
    )
    stub = _StubVerifier(result=skipped)
    service = VerifierService(bus=bus, storage=storage, verifiers=(stub,))
    await service.on_subscribe()

    with structlog.testing.capture_logs() as caplog:
        await bus.publish(
            SUBJECT_LINKAGE_PROPOSED,
            _envelope(linkage.id).model_dump_json().encode(),
        )
        await asyncio.sleep(0.1)

    assert "verifier.no_qualified_results" in _events(caplog)
    row = await storage.get_linkage(linkage.id)
    assert row is not None
    assert row.state == LinkageState.PROPOSED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skip_promotion_illegal_transition(storage: SQLiteStorage) -> None:
    bus = MemoryBus()
    linkage = await storage.insert_proposed_linkage(_A, _B, method="test", score=0.5, evidence={})
    # Operator beat the verifier to it — already terminal.
    await storage.transition_linkage(linkage.id, LinkageState.CONFIRMED, decided_by="anti")

    # Score well above floor so we reach _promote_to_suspected.
    strong = VerificationResult(
        method="stub",
        score=0.95,
        confidence=1.0,
    )
    stub = _StubVerifier(result=strong)
    service = VerifierService(bus=bus, storage=storage, verifiers=(stub,))
    await service.on_subscribe()

    with structlog.testing.capture_logs() as caplog:
        await bus.publish(
            SUBJECT_LINKAGE_PROPOSED,
            _envelope(linkage.id).model_dump_json().encode(),
        )
        await asyncio.sleep(0.1)

    assert "verifier.skip_promotion_illegal_transition" in _events(caplog)
    row = await storage.get_linkage(linkage.id)
    assert row is not None
    assert row.state == LinkageState.CONFIRMED  # untouched
