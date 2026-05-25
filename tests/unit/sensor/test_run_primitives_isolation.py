"""Unit test: per-primitive sibling isolation inside ``_run_primitives``.

The structural guarantee is the per-primitive ``try`` block in
``StylometricSensor._run_primitives``: a ``RuntimeError`` in one primitive's
``compute`` must NOT prevent sibling primitives from producing observations
for the SAME envelope.

Tested directly against ``_run_primitives`` so it's milliseconds and has
no coupling to pool timing, audit-chain serialization, or bus delivery.
The integration-tier counterpart in
``tests/integration/test_stylometric_e2e_sqlite.py::test_dispatch_drains_under_primitive_failure``
covers the lifecycle/throughput angle; the *invariant* itself lives here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest

from eyenet.bus import MemoryBus
from eyenet.contracts._base import TraceContext
from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.models import MessageTable
from eyenet.models._base import new_uuid7
from eyenet.sensor.stylometric import StylometricSensor
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
_ACTOR_KEY = "actor:" + "a" * 64


async def _seed_one_actor_with_bodies(
    storage: BaseRepository,
    bodies: list[str],
) -> tuple[UUID, str]:
    """Seed one actor + N bodies. Returns (actor_id, evidence_ref_for_latest)."""
    source_id = await storage.upsert_source(
        kind=SourceKind.TELEGRAM,
        display_name="telegram:isolation_test",
        created_at=_NOW,
    )
    group_id = await storage.upsert_group(
        source_id=source_id,
        platform_groupid="-100",
        kind=GroupKind.CHAT,
        title="iso",
        seen_at=_NOW,
    )
    actor_id = await storage.upsert_actor(
        source_id=source_id,
        actor_key=_ACTOR_KEY,
        platform_userid="iso",
        handle=None,
        display_name=None,
        seen_at=_NOW,
    )
    latest_ref = ""
    for i, body in enumerate(bodies):
        ref = f"telegram:-100:{i}"
        await storage.put_message(
            MessageTable(
                id=new_uuid7(),
                source_id=source_id,
                group_id=group_id,
                actor_id=actor_id,
                platform_msgid=str(i),
                evidence_ref=ref,
                body=body,
                length_chars=len(body),
                length_words=len(body.split()),
                sent_at_source=_NOW,
                ingested_at=_NOW,
            )
        )
        latest_ref = ref
    return actor_id, latest_ref


@pytest.mark.unit
@pytest.mark.asyncio
async def test_broken_primitive_does_not_suppress_sibling_observations(
    tmp_path: Path,
) -> None:
    """With ``mattr.compute`` patched to raise, OTHER primitives still
    write Observation rows for the same envelope. The structural guarantee
    of the per-primitive try block in ``_run_primitives``.
    """
    storage = get_repository(in_memory=True)
    # Enough corpus that the window-based stylometric primitives have
    # material to compute over (the minimum corpus floors are ~30-50
    # messages for the M2 stylometric set).
    bodies = [
        "hola que tal compita todo bien aca",
        "muy bien gracias por preguntar amigo",
        "che mira esto que esta pasando",
    ] * 25
    actor_id, latest_ref = await _seed_one_actor_with_bodies(storage, bodies)

    env = RawMessageEnvelope(
        source=SourceKind.TELEGRAM,
        instance_id="iso_test",
        evidence_ref=latest_ref,
        actor_key=_ACTOR_KEY,
        platform_groupid="-100",
        platform_msgid=str(len(bodies) - 1),
        sent_at_source=_NOW,
        collected_at=_NOW,
        length_chars=0,
        length_words=0,
        body_sha256="0" * 64,
        is_forward=False,
        has_attachment=False,
        trace_context=TraceContext(traceparent="00-" + "0" * 32 + "-" + "0" * 16 + "-00"),
    )

    sensor = StylometricSensor(bus=MemoryBus(), storage=storage)

    # Patch one specific primitive's compute to raise on every call.
    # The sibling primitives must still write Observation rows for this
    # envelope — the per-primitive try/except in _run_primitives is the
    # only thing that makes that true.
    with patch(
        "eyenet.sensor.primitives.mattr.compute",
        side_effect=RuntimeError("boom"),
    ):
        await sensor._run_primitives(actor_id, env, bodies[-1])

    # Read every observation row landed for this actor in this dispatch
    # window. mattr's row must NOT be there (raised); at least one sibling
    # MUST be there (the isolation invariant).
    async with storage.session() as session:
        from sqlmodel import select

        from eyenet.models import ObservationTable

        result = await session.exec(
            select(ObservationTable).where(ObservationTable.actor_id == actor_id)
        )
        rows = list(result.all())

    primitive_names = {r.primitive_name for r in rows}
    assert "mattr" not in primitive_names, (
        "broken primitive should not have written an observation"
    )
    assert len(primitive_names) >= 1, (
        "at least one sibling primitive must produce an observation despite "
        f"mattr raising — got: {primitive_names}"
    )
