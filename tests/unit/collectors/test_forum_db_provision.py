# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forum identity on the DB pool: provision -> claim -> materialize cookie jar."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from eyenet.collectors.base._credentials import materialize_forum_session
from eyenet.contracts.enums import SourceKind
from eyenet.crypto import load_session_key
from eyenet.identity_pool._provision import SessionValidationError, provision_identity
from eyenet.identity_pool.db import DbIdentityPool
from eyenet.storage.factory import get_repository

# Minimal Netscape cookies.txt: one session cookie. Real tabs, not spaces.
_COOKIES_TXT = "# Netscape HTTP Cookie File\nforum.test\tFALSE\t/\tTRUE\t9999999999\tsid\tabc123\n"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_provision_claim_materialize(tmp_path: Path) -> None:
    storage = get_repository(in_memory=True)
    session_key = load_session_key(tmp_path)
    source_id = await storage.upsert_source(
        kind=SourceKind.FORUM,
        display_name="forum:db",
        created_at=datetime.now(tz=UTC),
    )

    row = await provision_identity(
        storage=storage,
        session_key=session_key,
        data_dir=tmp_path,
        name="db_forum",
        source_id=source_id,
        source_kind=SourceKind.FORUM,
        secret_blob=_COOKIES_TXT.encode("utf-8"),
        source_config={
            "forum_base_url": "https://forum.test",
            "forum_thread_urls": ["Thread-x--1"],
        },
    )

    # The at-rest blob is encrypted: the plaintext cookie value is NOT on disk.
    assert b"abc123" not in Path(row.session_path).read_bytes()

    entry = await DbIdentityPool(storage).claim("db_forum")
    assert entry.source == SourceKind.FORUM
    assert entry.forum_base_url == "https://forum.test"
    assert entry.forum_thread_urls == ["Thread-x--1"]

    # Decrypt-on-boot: session_path -> the live cookie jar.
    cookies = materialize_forum_session(entry, session_key)
    assert cookies.get("sid") == "abc123"

    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_provision_rejects_non_cookie_blob(tmp_path: Path) -> None:
    storage = get_repository(in_memory=True)
    session_key = load_session_key(tmp_path)
    source_id = await storage.upsert_source(
        kind=SourceKind.FORUM,
        display_name="forum:bad",
        created_at=datetime.now(tz=UTC),
    )

    with pytest.raises(SessionValidationError):
        await provision_identity(
            storage=storage,
            session_key=session_key,
            data_dir=tmp_path,
            name="bad_forum",
            source_id=source_id,
            source_kind=SourceKind.FORUM,
            secret_blob=b"this is not a cookies.txt file",
            source_config={"forum_base_url": "https://forum.test"},
        )

    await storage.close()
