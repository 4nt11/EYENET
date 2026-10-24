# SPDX-License-Identifier: AGPL-3.0-or-later
"""StealerMixin: processing-state upsert + the replay work-list (list_unprocessed)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eyenet.contracts.enums import AttachmentKind
from eyenet.contracts.message import AttachmentRow
from eyenet.models.stealer import STEALER_DONE, STEALER_FAILED, STEALER_RUNNING
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_CAT = "stealer_logs"


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _put(storage: BaseRepository, *, sha: str, storage_uri: str | None, category: str | None):
    return await storage.put_attachment(
        AttachmentRow(
            message_id=uuid4(),
            kind=AttachmentKind.DOCUMENT,
            mime="application/x-rar-compressed",
            size_bytes=1_000_000,
            sha256=sha,
            storage_uri=storage_uri,
            category=category,
        )
    )


async def test_set_get_bumps_attempts(storage: BaseRepository) -> None:
    aid = await _put(storage, sha="a" * 64, storage_uri="blob/a.bin", category=_CAT)
    assert await storage.get_stealer_processing(aid) is None

    await storage.set_stealer_processing(aid, state=STEALER_RUNNING)
    row = await storage.get_stealer_processing(aid)
    assert row is not None and row.state == STEALER_RUNNING and row.attempts == 1

    await storage.set_stealer_processing(aid, state=STEALER_DONE, creds_extracted=42)
    row = await storage.get_stealer_processing(aid)
    assert row is not None
    assert (row.state, row.creds_extracted, row.attempts) == (STEALER_DONE, 42, 2)
    await storage.close()


async def test_list_unprocessed_excludes_done_and_unstored(storage: BaseRepository) -> None:
    never = await _put(storage, sha="b" * 64, storage_uri="blob/b.bin", category=_CAT)
    failed = await _put(storage, sha="c" * 64, storage_uri="blob/c.bin", category=_CAT)
    done = await _put(storage, sha="d" * 64, storage_uri="blob/d.bin", category=_CAT)
    await _put(storage, sha="e" * 64, storage_uri=None, category=_CAT)  # no blob
    await _put(storage, sha="f" * 64, storage_uri="blob/f.bin", category=None)  # unmarked
    await storage.set_stealer_processing(failed, state=STEALER_FAILED, error="bad pw")
    await storage.set_stealer_processing(done, state=STEALER_DONE, creds_extracted=10)

    work = await storage.list_unprocessed_stealer_attachments(_CAT, limit=20)
    ids = {r.id for r in work}
    assert never in ids  # never tried
    assert failed in ids  # retry a failure
    assert done not in ids  # already done
    assert len(ids) == 2  # the unstored + unmarked ones excluded too
    await storage.close()


def test_states_are_distinct() -> None:
    assert len({STEALER_RUNNING, STEALER_DONE, STEALER_FAILED}) == 3
