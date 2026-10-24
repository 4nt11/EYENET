# SPDX-License-Identifier: AGPL-3.0-or-later
"""StealerProcessorService orchestration: skip-if-done, no-blob→failed, success→done.

The heavy decrypt/extract/ingest (process_archive) is stubbed — this covers the
service's state machine, not the subprocess pipeline (that's integration)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eyenet.bus.memory import MemoryBus
from eyenet.contracts.enums import AttachmentKind
from eyenet.contracts.message import AttachmentRow
from eyenet.models.stealer import STEALER_DONE, STEALER_FAILED
from eyenet.stealer import service as service_mod
from eyenet.stealer.pipeline import ProcessResult
from eyenet.stealer.service import StealerProcessorService
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_CAT = "stealer_logs"


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _svc(storage: BaseRepository) -> StealerProcessorService:
    return StealerProcessorService(bus=MemoryBus(), storage=storage)


async def _put_blob(storage: BaseRepository, *, uri: str | None) -> object:
    return await storage.put_attachment(
        AttachmentRow(
            message_id=uuid4(),
            kind=AttachmentKind.DOCUMENT,
            mime="application/x-rar-compressed",
            size_bytes=1,
            sha256="a" * 64,
            storage_uri=uri,
            category=_CAT,
        )
    )


async def test_success_marks_done_with_count(
    storage: BaseRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    aid = await _put_blob(storage, uri="/blobs/x.rar")
    calls: list[object] = []

    def _fake(**kwargs: object) -> ProcessResult:
        calls.append(kwargs["blob_path"])
        return ProcessResult(ok=True, creds_inserted=777, password_used="@x")

    monkeypatch.setattr(service_mod, "process_archive", _fake)
    await _svc(storage)._process_attachment(aid)

    row = await storage.get_stealer_processing(aid)
    assert row is not None and row.state == STEALER_DONE and row.creds_extracted == 777
    assert len(calls) == 1
    await storage.close()


async def test_skip_when_already_done(
    storage: BaseRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    aid = await _put_blob(storage, uri="/blobs/x.rar")
    await storage.set_stealer_processing(aid, state=STEALER_DONE, creds_extracted=5)
    called = False

    def _fake(**_kwargs: object) -> ProcessResult:
        nonlocal called
        called = True
        return ProcessResult(ok=True, creds_inserted=0, password_used=None)

    monkeypatch.setattr(service_mod, "process_archive", _fake)
    await _svc(storage)._process_attachment(aid)
    assert called is False  # done archives are not reprocessed
    await storage.close()


async def test_missing_blob_marks_failed(storage: BaseRepository) -> None:
    aid = await _put_blob(storage, uri=None)  # over-gate shell, no blob on disk
    await _svc(storage)._process_attachment(aid)
    row = await storage.get_stealer_processing(aid)
    assert row is not None and row.state == STEALER_FAILED
    await storage.close()


async def test_pipeline_failure_marks_failed(
    storage: BaseRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    aid = await _put_blob(storage, uri="/blobs/x.rar")

    def _fake(**_kwargs: object) -> ProcessResult:
        return ProcessResult(ok=False, creds_inserted=0, password_used=None, error="bad pw")

    monkeypatch.setattr(service_mod, "process_archive", _fake)
    await _svc(storage)._process_attachment(aid)
    row = await storage.get_stealer_processing(aid)
    assert row is not None and row.state == STEALER_FAILED and row.error == "bad pw"
    await storage.close()
