"""End-to-end audit chain test through SQLiteAuditStore."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from eyenet.contracts.audit import verify_chain
from eyenet.storage import SQLiteStorage


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chain_holds_over_100_events(tmp_path: Path) -> None:
    s = SQLiteStorage(tmp_path)
    try:
        for i in range(100):
            await s.audit.append(
                {
                    "event": "evidence_access",
                    "service": "engine",
                    "instance_id": "eng_1",
                    "subject_kind": "actor",
                    "at": datetime(2026, 5, 4, 12, i % 60, i // 60, tzinfo=UTC),
                }
            )
        rows = await s.audit.all()
        ok, broken = verify_chain(rows)
        assert ok
        assert broken is None
        assert len(rows) == 100
    finally:
        await s.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ndjson_mirror(tmp_path: Path) -> None:
    s = SQLiteStorage(tmp_path)
    try:
        await s.audit.append(
            {
                "event": "service.start",
                "service": "engine",
                "instance_id": "eng_1",
                "subject_kind": "service",
                "at": datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC),
            }
        )
    finally:
        await s.close()
    ndjson = tmp_path / "audit.ndjson"
    assert ndjson.exists()
    assert ndjson.stat().st_mode & 0o777 == 0o600
    content = ndjson.read_text("utf-8").strip().splitlines()
    assert len(content) == 1
