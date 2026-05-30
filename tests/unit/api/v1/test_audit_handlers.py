# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the M9.F4 audit read handlers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import text as sa_text

from eyenet.api.deps import CurrentUser
from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.audit.api_list_audit import audit_list
from eyenet.api.v1.audit.api_verify_audit import audit_verify
from eyenet.models._base import new_uuid7
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


def _page() -> CursorParams:
    return CursorParams(offset=0, limit=50, include_total=True)


async def _append(storage: BaseRepository, *, event: str, at: datetime, user=None) -> None:
    await storage.append_audit(
        {
            "id": new_uuid7(),
            "event": event,
            "service": "test",
            "instance_id": "t0",
            "system_user_id": user,
            "subject_kind": "test",
            "subject_id": None,
            "evidence_ref": None,
            "trace_id": None,
            "span_id": None,
            "payload": {},
            "at": at,
        }
    )


async def test_audit_list_filters_by_subject_and_user(
    storage: BaseRepository, now: datetime, mkuser: Callable[..., CurrentUser]
) -> None:
    u = uuid4()
    await _append(storage, event="eyenet.test.a", at=now, user=u)
    await _append(storage, event="eyenet.test.b", at=now, user=uuid4())
    by_subject = await audit_list(
        mkuser("read:audit"), storage, _page(), None, "eyenet.test.a", None, None
    )
    assert {r.subject for r in by_subject.items} == {"eyenet.test.a"}
    assert by_subject.estimated_total == 1

    by_user = await audit_list(mkuser("read:audit"), storage, _page(), u, None, None, None)
    assert {r.user_id for r in by_user.items} == {u}


async def test_audit_verify_clean(
    storage: BaseRepository, now: datetime, mkuser: Callable[..., CurrentUser]
) -> None:
    await _append(storage, event="eyenet.test.one", at=now)
    await _append(storage, event="eyenet.test.two", at=now)
    result = await audit_verify(mkuser("read:audit"), storage)
    assert result.verified is True
    assert result.first_break is None
    assert result.rows_checked == 2


async def test_audit_verify_detects_tamper(
    storage: BaseRepository, now: datetime, mkuser: Callable[..., CurrentUser]
) -> None:
    await _append(storage, event="eyenet.test.one", at=now)
    await _append(storage, event="eyenet.test.two", at=now)
    async with storage.audit_engine.begin() as conn:  # type: ignore[attr-defined]
        await conn.execute(
            sa_text(
                "UPDATE audit_log SET self_hash = :h "
                "WHERE rowid = (SELECT MIN(rowid) FROM audit_log)"
            ),
            {"h": "f" * 64},
        )
    result = await audit_verify(mkuser("read:audit"), storage)
    assert result.verified is False
    assert result.first_break is not None
    assert result.first_break.actual_hash == "f" * 64
