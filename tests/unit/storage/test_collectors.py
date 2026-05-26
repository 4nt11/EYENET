"""Storage tests for CollectorTable CRUD + state writes (M9.C3, MODELS §2.19).

Default fixture (BaseRepository typed, in-memory via factory). The
SQLite-impl-specific CHECK probes live in ``test_collectors_sqlite.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from eyenet.contracts.collector import CollectorRow
from eyenet.contracts.enums import (
    CollectorDesiredState,
    CollectorObservedState,
    IdentityState,
    SourceKind,
)
from eyenet.models.identity import IdentityTable
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 5, 25, tzinfo=UTC)
_OPERATOR = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _make_source(storage: BaseRepository, name: str = "ALPHA") -> UUID:
    return await storage.upsert_source(
        kind=SourceKind.TELEGRAM,
        display_name=f"telegram:{name}",
        created_at=_NOW,
    )


async def _make_identity(
    storage: BaseRepository,
    source_id: UUID,
    name: str,
) -> UUID:
    # No public abstract method for identity creation yet; insert via the
    # escape-hatch session (MODELS §2.1 — identities are TOML-loaded in
    # production, so there's no upsert_identity surface).
    async with storage.session() as session:
        row = IdentityTable(
            name=name,
            source_id=source_id,
            session_path=f"/tmp/{name}.session",  # noqa: S108 — test stub, never opened
            state=IdentityState.AVAILABLE,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


# --- create + read ----------------------------------------------------


@pytest.mark.unit
async def test_create_collector_round_trip(storage: BaseRepository) -> None:
    source_id = await _make_source(storage)
    identity_id = await _make_identity(storage, source_id, "tg_alpha")
    row = await storage.create_collector(
        instance_name="tg_alpha_collector_01",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=identity_id,
        config={"kind": "telegram", "monitor_chat_ids": [-100, -101]},
        created_at=_NOW,
        created_by_user_id=_OPERATOR,
    )
    assert row.instance_name == "tg_alpha_collector_01"
    assert row.kind is SourceKind.TELEGRAM
    assert row.source_id == source_id
    assert row.identity_id == identity_id
    # Fresh rows start STOPPED/STOPPED per API_PLAN §4.11.2.
    assert row.desired_state is CollectorDesiredState.STOPPED
    assert row.observed_state is CollectorObservedState.STOPPED
    assert row.restart_count == 0
    assert row.last_error_type is None
    assert row.last_error_message is None
    assert row.config == {"kind": "telegram", "monitor_chat_ids": [-100, -101]}


@pytest.mark.unit
async def test_get_collector_returns_none_for_unknown(
    storage: BaseRepository,
) -> None:
    assert await storage.get_collector(uuid4()) is None


@pytest.mark.unit
async def test_list_collectors_ordered_by_created_at(
    storage: BaseRepository,
) -> None:
    source_id = await _make_source(storage)
    id_a = await _make_identity(storage, source_id, "tg_a")
    id_b = await _make_identity(storage, source_id, "tg_b")
    older = datetime(2025, 1, 1, tzinfo=UTC)
    newer = datetime(2026, 1, 1, tzinfo=UTC)
    await storage.create_collector(
        instance_name="newer_one",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=id_b,
        config={"kind": "telegram"},
        created_at=newer,
        created_by_user_id=_OPERATOR,
    )
    await storage.create_collector(
        instance_name="older_one",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=id_a,
        config={"kind": "telegram"},
        created_at=older,
        created_by_user_id=_OPERATOR,
    )
    rows = await storage.list_collectors()
    assert [r.instance_name for r in rows] == ["older_one", "newer_one"]


# --- identity uniqueness ---------------------------------------------


@pytest.mark.unit
async def test_identity_id_uniqueness_enforced(storage: BaseRepository) -> None:
    # API_PLAN §4.11.3: no two collectors share an Identity. Ever.
    source_id = await _make_source(storage)
    identity_id = await _make_identity(storage, source_id, "tg_shared")
    await storage.create_collector(
        instance_name="first",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=identity_id,
        config={"kind": "telegram"},
        created_at=_NOW,
        created_by_user_id=_OPERATOR,
    )
    with pytest.raises(IntegrityError):
        await storage.create_collector(
            instance_name="second",
            kind=SourceKind.TELEGRAM,
            source_id=source_id,
            identity_id=identity_id,  # same identity → reject
            config={"kind": "telegram"},
            created_at=_NOW,
            created_by_user_id=_OPERATOR,
        )


@pytest.mark.unit
async def test_instance_name_uniqueness_enforced(storage: BaseRepository) -> None:
    source_id = await _make_source(storage)
    id_a = await _make_identity(storage, source_id, "tg_a")
    id_b = await _make_identity(storage, source_id, "tg_b")
    await storage.create_collector(
        instance_name="collide",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=id_a,
        config={"kind": "telegram"},
        created_at=_NOW,
        created_by_user_id=_OPERATOR,
    )
    with pytest.raises(IntegrityError):
        await storage.create_collector(
            instance_name="collide",  # duplicate instance_name → reject
            kind=SourceKind.TELEGRAM,
            source_id=source_id,
            identity_id=id_b,
            config={"kind": "telegram"},
            created_at=_NOW,
            created_by_user_id=_OPERATOR,
        )


# --- desired_state writes --------------------------------------------


@pytest.mark.unit
async def test_set_desired_state_transitions(storage: BaseRepository) -> None:
    source_id = await _make_source(storage)
    identity_id = await _make_identity(storage, source_id, "tg_a")
    row = await storage.create_collector(
        instance_name="tg_a",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=identity_id,
        config={"kind": "telegram"},
        created_at=_NOW,
        created_by_user_id=_OPERATOR,
    )
    for target in (
        CollectorDesiredState.RUNNING,
        CollectorDesiredState.STOPPED,
        CollectorDesiredState.DISABLED,
    ):
        updated = await storage.set_collector_desired_state(
            collector_id=row.id,
            desired_state=target,
        )
        assert updated.desired_state is target
        # observed_state must NOT be touched by desired-state writes.
        assert updated.observed_state is CollectorObservedState.STOPPED


@pytest.mark.unit
async def test_set_desired_state_unknown_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.set_collector_desired_state(
            collector_id=uuid4(),
            desired_state=CollectorDesiredState.RUNNING,
        )


# --- observed_state writes -------------------------------------------


@pytest.mark.unit
async def test_record_observed_running_clears_stale_errors(
    storage: BaseRepository,
) -> None:
    source_id = await _make_source(storage)
    identity_id = await _make_identity(storage, source_id, "tg_a")
    row = await storage.create_collector(
        instance_name="tg_a",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=identity_id,
        config={"kind": "telegram"},
        created_at=_NOW,
        created_by_user_id=_OPERATOR,
    )
    # Crash first, then recover. The error pair must be cleared on
    # the next non-CRASHED transition that does NOT explicitly pass
    # error fields.
    await storage.record_collector_observed_state(
        collector_id=row.id,
        observed_state=CollectorObservedState.CRASHED,
        last_error_type="FloodWaitError",
        last_error_message="A wait of 86400 seconds is required",
        restart_count=1,
    )
    recovered = await storage.record_collector_observed_state(
        collector_id=row.id,
        observed_state=CollectorObservedState.RUNNING,
        last_heartbeat_at=_NOW,
        restart_count=1,
    )
    assert recovered.observed_state is CollectorObservedState.RUNNING
    assert recovered.last_error_type is None
    assert recovered.last_error_message is None
    assert recovered.last_heartbeat_at == _NOW


@pytest.mark.unit
async def test_record_observed_crashed_requires_error_pair(
    storage: BaseRepository,
) -> None:
    source_id = await _make_source(storage)
    identity_id = await _make_identity(storage, source_id, "tg_a")
    row = await storage.create_collector(
        instance_name="tg_a",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=identity_id,
        config={"kind": "telegram"},
        created_at=_NOW,
        created_by_user_id=_OPERATOR,
    )
    with pytest.raises(ValueError, match="last_error"):
        await storage.record_collector_observed_state(
            collector_id=row.id,
            observed_state=CollectorObservedState.CRASHED,
            # No error fields supplied — must reject.
        )


@pytest.mark.unit
async def test_record_observed_unknown_collector_raises(
    storage: BaseRepository,
) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.record_collector_observed_state(
            collector_id=uuid4(),
            observed_state=CollectorObservedState.RUNNING,
        )


@pytest.mark.unit
async def test_record_observed_restart_count_preserved_when_omitted(
    storage: BaseRepository,
) -> None:
    source_id = await _make_source(storage)
    identity_id = await _make_identity(storage, source_id, "tg_a")
    row = await storage.create_collector(
        instance_name="tg_a",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=identity_id,
        config={"kind": "telegram"},
        created_at=_NOW,
        created_by_user_id=_OPERATOR,
    )
    # First bump restart_count to 3 via an explicit CRASHED transition.
    await storage.record_collector_observed_state(
        collector_id=row.id,
        observed_state=CollectorObservedState.CRASHED,
        last_error_type="X",
        last_error_message="y",
        restart_count=3,
    )
    # Transition to STARTING WITHOUT passing restart_count — must preserve 3.
    after = await storage.record_collector_observed_state(
        collector_id=row.id,
        observed_state=CollectorObservedState.STARTING,
    )
    assert after.restart_count == 3


# --- delete -----------------------------------------------------------


@pytest.mark.unit
async def test_delete_collector_removes_row(storage: BaseRepository) -> None:
    source_id = await _make_source(storage)
    identity_id = await _make_identity(storage, source_id, "tg_a")
    row = await storage.create_collector(
        instance_name="tg_a",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=identity_id,
        config={"kind": "telegram"},
        created_at=_NOW,
        created_by_user_id=_OPERATOR,
    )
    await storage.delete_collector(row.id)
    assert await storage.get_collector(row.id) is None


@pytest.mark.unit
async def test_delete_unknown_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.delete_collector(uuid4())


# --- identity_id one-to-one is durable across deletion ---------------


@pytest.mark.unit
async def test_identity_id_reclaimable_after_delete(
    storage: BaseRepository,
) -> None:
    # Once a collector is deleted, its identity must be re-bindable to
    # a new collector. This is the "free the lease" property.
    source_id = await _make_source(storage)
    identity_id = await _make_identity(storage, source_id, "tg_a")
    first = await storage.create_collector(
        instance_name="first",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=identity_id,
        config={"kind": "telegram"},
        created_at=_NOW,
        created_by_user_id=_OPERATOR,
    )
    await storage.delete_collector(first.id)
    second = await storage.create_collector(
        instance_name="second",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=identity_id,
        config={"kind": "telegram"},
        created_at=_NOW,
        created_by_user_id=_OPERATOR,
    )
    assert second.identity_id == identity_id
    assert second.id != first.id


@pytest.mark.unit
async def test_collector_row_contract_shape(storage: BaseRepository) -> None:
    # CollectorRow validates as a DbRowBase Pydantic model.
    source_id = await _make_source(storage)
    identity_id = await _make_identity(storage, source_id, "tg_a")
    row = await storage.create_collector(
        instance_name="tg_a",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=identity_id,
        config={"kind": "telegram"},
        created_at=_NOW,
        created_by_user_id=_OPERATOR,
        notes="initial commission",
    )
    assert isinstance(row, CollectorRow)
    dumped = row.model_dump()
    assert dumped["instance_name"] == "tg_a"
    assert dumped["notes"] == "initial commission"
