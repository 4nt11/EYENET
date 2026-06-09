# SPDX-License-Identifier: AGPL-3.0-or-later
"""M9.B2 SQLite-CHECK probe — the tier-conditional grant/ack DB constraint.

SQLite-impl probe per CLAUDE.md §2.3: env-pinned + ``_sqlite`` filename suffix
so a future MySQL/Postgres mirror sits alongside. Asserts the DB-level CHECK
``tier = 'NORMAL' OR (grant_id IS NOT NULL AND acknowledgment_id IS NOT NULL)``
fires on a raw insert that bypasses ``record_access``'s typed guard — defense
in depth. The CHECK compares against the uppercase StrEnum NAME because
SQLModel persists a StrEnum by name, not value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from eyenet.contracts.enums import FileServedVia, SensitivityTier
from eyenet.models.file_access import FileAccessJournalTable
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.storage.sqlmodel_repo._helpers import safe_session


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> BaseRepository:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    return get_repository(data_dir=tmp_path)


def _row(**overrides: object) -> FileAccessJournalTable:
    base: dict[str, object] = {
        "user_id": uuid4(),
        "grant_id": None,
        "content_hash": b"\x11" * 32,
        "content_size": 10,
        "content_mime": "application/pdf",
        "tier": SensitivityTier.RESTRICTED,
        "served_at": datetime.now(tz=UTC),
        "served_via": FileServedVia.INLINE_JSON,
        "acknowledgment_id": None,
        "operator_signature": b"\x00" * 64,
        "signing_pubkey_fingerprint": "0123456789abcdef",
        "prev_journal_hash": b"\x00" * 32,
        "self_hash": b"\x01" * 32,
    }
    base.update(overrides)
    return FileAccessJournalTable(**base)  # type: ignore[arg-type]


async def _insert(storage: BaseRepository, row: FileAccessJournalTable) -> None:
    async with safe_session(storage._audit_session_factory) as session:  # type: ignore[attr-defined]
        session.add(row)
        await session.commit()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_fires_on_restricted_without_grant_ack(storage: BaseRepository) -> None:
    """Raw insert of a RESTRICTED row with NULL grant/ack is refused by the DB."""
    row = _row(tier=SensitivityTier.RESTRICTED, grant_id=None, acknowledgment_id=None)
    with pytest.raises(IntegrityError):
        await _insert(storage, row)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_allows_restricted_with_grant_and_ack(storage: BaseRepository) -> None:
    """A RESTRICTED row WITH both grant_id and acknowledgment_id satisfies the CHECK."""
    await _insert(
        storage,
        _row(tier=SensitivityTier.RESTRICTED, grant_id=uuid4(), acknowledgment_id=uuid4()),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_allows_normal_without_grant_ack(storage: BaseRepository) -> None:
    """A NORMAL row needs neither grant nor ack — the CHECK passes."""
    await _insert(storage, _row(tier=SensitivityTier.NORMAL, grant_id=None, acknowledgment_id=None))
