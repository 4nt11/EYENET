"""Unit tests for actor upsert + resolve helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session

from eyenet.contracts.enums import SourceKind
from eyenet.storage.actors import resolve_actor_id, upsert_actor, upsert_source
from eyenet.storage.engines import StoreName, create_all_for, open_in_memory_engine

_NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def messages_engine() -> Engine:
    engine = open_in_memory_engine()
    create_all_for(StoreName.MESSAGES, engine)
    return engine


@pytest.fixture
def source_id(messages_engine: Engine) -> UUID:
    with Session(messages_engine) as session:
        sid = upsert_source(
            session,
            kind=SourceKind.TELEGRAM,
            display_name="telegram:test",
            created_at=_NOW,
        )
        session.commit()
    return sid


@pytest.mark.unit
def test_resolve_unknown_returns_none(messages_engine: Engine) -> None:
    with Session(messages_engine) as session:
        assert resolve_actor_id(session, "actor:" + "a" * 64) is None


@pytest.mark.unit
def test_upsert_and_resolve(messages_engine: Engine, source_id: UUID) -> None:
    actor_key = "actor:" + "b" * 64
    with Session(messages_engine) as session:
        uid = upsert_actor(
            session,
            source_id=source_id,
            actor_key=actor_key,
            platform_userid="12345",
            handle="@testuser",
            display_name="Test User",
            seen_at=_NOW,
        )
        session.commit()

    with Session(messages_engine) as session:
        resolved = resolve_actor_id(session, actor_key)

    assert resolved == uid


@pytest.mark.unit
def test_upsert_idempotent(messages_engine: Engine, source_id: UUID) -> None:
    actor_key = "actor:" + "c" * 64
    with Session(messages_engine) as session:
        uid1 = upsert_actor(
            session,
            source_id=source_id,
            actor_key=actor_key,
            platform_userid="99",
            handle=None,
            display_name=None,
            seen_at=_NOW,
        )
        session.commit()

    with Session(messages_engine) as session:
        uid2 = upsert_actor(
            session,
            source_id=source_id,
            actor_key=actor_key,
            platform_userid="99",
            handle="@newhandle",
            display_name="New Name",
            seen_at=_NOW,
        )
        session.commit()

    assert uid1 == uid2


@pytest.mark.unit
def test_upsert_updates_handle(messages_engine: Engine, source_id: UUID) -> None:
    actor_key = "actor:" + "d" * 64
    with Session(messages_engine) as session:
        upsert_actor(
            session,
            source_id=source_id,
            actor_key=actor_key,
            platform_userid="77",
            handle="@old",
            display_name=None,
            seen_at=_NOW,
        )
        session.commit()

    from sqlmodel import select

    from eyenet.models import ActorTable

    with Session(messages_engine) as session:
        upsert_actor(
            session,
            source_id=source_id,
            actor_key=actor_key,
            platform_userid="77",
            handle="@new",
            display_name=None,
            seen_at=_NOW,
        )
        session.commit()

        row = session.exec(select(ActorTable).where(ActorTable.actor_key == actor_key)).first()
        assert row is not None
        assert row.current_handle == "@new"
