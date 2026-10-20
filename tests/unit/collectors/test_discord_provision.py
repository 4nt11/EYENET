"""The Discord provisioning path end to end: provision -> claim -> materialize.

Proves the encrypted blob round-trips through provision_identity + the DB-backed pool
back into the collector's DiscordSession, and that source_config maps to the discord_*
IdentityFileEntry fields the collector reads.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eyenet.collectors.base._credentials import materialize_discord_session
from eyenet.contracts.enums import SourceKind
from eyenet.crypto import load_session_key
from eyenet.identity_pool._provision import provision_identity
from eyenet.identity_pool.db import DbIdentityPool
from eyenet.storage.factory import get_repository

_NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_provision_claim_materialize(tmp_path: Path) -> None:
    storage = get_repository(in_memory=True)
    session_key = load_session_key(tmp_path)
    source_id = await storage.upsert_source(
        kind=SourceKind.DISCORD, display_name="discord:test", created_at=_NOW
    )
    blob = json.dumps({
        "token": "TOK", "cookie": "cf_clearance=x; locale=en-US",
        "super_properties": "eyJvcyI6IkxpbnV4In0=", "user_agent": "Firefox/157",
        "installation_id": "iid.abc", "capabilities": 1734653,
    }).encode()
    # source_config keys are the discord_* IdentityFileEntry fields (DbPool splats them)
    source_config: dict[str, object] = {
        "discord_impersonate": "firefox147",
        "discord_delay_min": 1.0,
        "discord_delay_max": 1.5,
        "discord_enable_waf_bypass": True,
    }

    await provision_identity(
        storage=storage, session_key=session_key, data_dir=tmp_path,
        name="dc-test", source_id=source_id, source_kind=SourceKind.DISCORD,
        secret_blob=blob, source_config=source_config,
    )

    # claim through the DB-backed pool -> an IdentityFileEntry with the discord_* config
    entry = await DbIdentityPool(storage).claim("dc-test")
    assert entry.source == SourceKind.DISCORD
    assert entry.discord_impersonate == "firefox147"
    assert entry.discord_delay_max == 1.5
    assert entry.discord_enable_waf_bypass is True

    # decrypt the blob back into the collector's credential set
    ds = materialize_discord_session(entry, session_key)
    assert ds.token == "TOK"
    assert ds.cookie.startswith("cf_clearance=")
    assert ds.capabilities == 1734653
