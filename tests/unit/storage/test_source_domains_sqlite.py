"""SQLite-pinned schema CHECK probes for source_domain (MODELS §2.26).

These tests bypass :class:`SourcesMixin` (which normalizes / overlap-checks
before INSERT) and write raw rows via the sync engine to verify the SQL
CHECK constraints fire as the backstop they're meant to be.

The ``_sqlite`` filename suffix follows CLAUDE.md §2.3 Rule 2: future
MySQL/Postgres mirror files sit alongside without collision.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from eyenet.contracts.enums import SourceDomainPatternKind, SourceKind
from eyenet.models.source import SourceTable
from eyenet.models.source_domain import SourceDomainTable
from eyenet.storage.factory import get_repository

_NOW = datetime(2026, 5, 25, tzinfo=UTC)


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> Session:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    storage = get_repository(in_memory=True)
    return Session(storage.sync_engine)  # type: ignore[attr-defined]


def _make_source(session: Session, name: str = "ALPHA") -> UUID:
    src = SourceTable(
        kind=SourceKind.FORUM,
        display_name=name,
        created_at=_NOW,
    )
    session.add(src)
    session.commit()
    session.refresh(src)
    return src.id


# --- CHECK constraints -----------------------------------------------


@pytest.mark.unit
def test_empty_pattern_rejected(session: Session) -> None:
    src = _make_source(session)
    session.add(
        SourceDomainTable(
            source_id=src,
            pattern="",
            pattern_kind=SourceDomainPatternKind.EXACT,
            is_primary=False,
            created_at=_NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_uppercase_pattern_rejected(session: Session) -> None:
    src = _make_source(session)
    session.add(
        SourceDomainTable(
            source_id=src,
            pattern="FOO.COM",  # CHECK pattern = lower(pattern)
            pattern_kind=SourceDomainPatternKind.EXACT,
            is_primary=False,
            created_at=_NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_star_in_pattern_rejected(session: Session) -> None:
    src = _make_source(session)
    session.add(
        SourceDomainTable(
            source_id=src,
            pattern="*.foo.com",  # wildcards store the parent only
            pattern_kind=SourceDomainPatternKind.SUBDOMAIN_WILDCARD,
            is_primary=False,
            created_at=_NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_empty_notes_rejected(session: Session) -> None:
    src = _make_source(session)
    session.add(
        SourceDomainTable(
            source_id=src,
            pattern="foo.com",
            pattern_kind=SourceDomainPatternKind.EXACT,
            is_primary=False,
            created_at=_NOW,
            notes="",  # CHECK notes IS NULL OR length(notes) > 0
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_removed_at_without_user_rejected(session: Session) -> None:
    src = _make_source(session)
    session.add(
        SourceDomainTable(
            source_id=src,
            pattern="foo.com",
            pattern_kind=SourceDomainPatternKind.EXACT,
            is_primary=False,
            created_at=_NOW,
            removed_at=_NOW,  # paired CHECK fails: no removed_by_user_id
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


# --- partial-unique primary ------------------------------------------


@pytest.mark.unit
def test_two_active_primaries_same_source_rejected(session: Session) -> None:
    src = _make_source(session)
    session.add(
        SourceDomainTable(
            source_id=src,
            pattern="forum.foo.com",
            pattern_kind=SourceDomainPatternKind.EXACT,
            is_primary=True,
            created_at=_NOW,
        )
    )
    session.commit()
    session.add(
        SourceDomainTable(
            source_id=src,
            pattern="legacy.foo.com",
            pattern_kind=SourceDomainPatternKind.EXACT,
            is_primary=True,  # second active primary for same source — REJECT
            created_at=_NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_two_primaries_different_sources_allowed(session: Session) -> None:
    src_a = _make_source(session, "A")
    src_b = _make_source(session, "B")
    session.add(
        SourceDomainTable(
            source_id=src_a,
            pattern="a.example",
            pattern_kind=SourceDomainPatternKind.EXACT,
            is_primary=True,
            created_at=_NOW,
        )
    )
    session.add(
        SourceDomainTable(
            source_id=src_b,
            pattern="b.example",
            pattern_kind=SourceDomainPatternKind.EXACT,
            is_primary=True,
            created_at=_NOW,
        )
    )
    session.commit()  # no IntegrityError — different sources


@pytest.mark.unit
def test_removed_primary_releases_uniqueness(session: Session) -> None:
    src = _make_source(session)
    operator = uuid4()
    session.add(
        SourceDomainTable(
            source_id=src,
            pattern="forum.foo.com",
            pattern_kind=SourceDomainPatternKind.EXACT,
            is_primary=True,
            created_at=_NOW,
        )
    )
    session.commit()
    # Mark the first row as removed.
    from sqlmodel import select

    row = session.exec(
        select(SourceDomainTable).where(
            SourceDomainTable.pattern == "forum.foo.com",
        ),
    ).one()
    row.removed_at = _NOW
    row.removed_by_user_id = operator
    session.add(row)
    session.commit()
    # Now a fresh active primary is allowed.
    session.add(
        SourceDomainTable(
            source_id=src,
            pattern="legacy.foo.com",
            pattern_kind=SourceDomainPatternKind.EXACT,
            is_primary=True,
            created_at=_NOW,
        )
    )
    session.commit()  # no IntegrityError
