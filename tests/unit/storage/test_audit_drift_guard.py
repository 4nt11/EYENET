"""The audit INSERT drift guard must fire when AuditLogRow fields diverge
from the hand-pinned `_AUDIT_INSERT_COLS` tuple.

The static INSERT exists to keep audit_log column names off the f-string
construction path. The drift guard exists so a future contract change that
adds or renames a field fails loud at the persistence layer instead of
silently dropping a column. This test proves the guard actually fires.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from eyenet.storage import SQLiteStorage


@pytest.mark.unit
def test_drift_guard_raises_when_audit_row_fields_diverge(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path)
    bad_cols = ("id", "event")  # deliberately incomplete

    row_data: dict[str, Any] = {
        "event": "service.start",
        "service": "test",
        "instance_id": "test_1",
        "system_user_id": None,
        "subject_kind": "service",
        "subject_id": None,
        "evidence_ref": None,
        "trace_id": None,
        "span_id": None,
        "payload": {},
        "at": datetime.now(tz=UTC),
    }

    # Drift guard is a property of the legacy SQLiteAuditStore raw-SQL
    # INSERT path; the new SQLModel ORM path generates the column list
    # from the table schema and has its own freshness guarantee.
    with (
        patch("eyenet.storage.audit._AUDIT_INSERT_COLS", bad_cols),
        pytest.raises(RuntimeError, match="drifted from _AUDIT_INSERT_COLS"),
    ):
        asyncio.run(storage.audit.append(row_data))
