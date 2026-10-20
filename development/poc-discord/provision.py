#!/usr/bin/env python3
"""Provision a Discord identity (+ source, collector, monitored channel) from the poc .env.

Reads the captured session out of this dir's .env, encrypts it into the IdentityTable
(the same seam telegram/forum use), and wires a collector row + one monitored-channel
membership so `eyenet collector discord --identity <name>` has something to do.

Run order on the LIVE system (NOT just this script):
  1. alembic upgrade head        # apply 0017_groupkind_guild (live groupkind lacks GUILD)
  2. rebuild/redeploy eyenet:base # ship the DiscordCollector code
  3. python provision.py          # this: reads .env, writes the identity + rows
  4. add `eyenet collector discord --identity <name>` to the supervisor config

Env it needs (beyond .env secrets):
  EYENET_PG_URL / EYENET_STORAGE_TYPE=postgres  -> point at the live DB
  PROVISION_DATA_DIR  (default: ../../data)      -> session key + blob location
  PROVISION_USER      (default: admin)           -> system_user for the collector row
  PROVISION_NAME      (default: dc-1)            -> identity/collector name

Dry run against a throwaway in-memory DB (no secrets needed, proves the wiring):
  python provision.py --dry
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
from datetime import UTC, datetime

from eyenet.contracts.collector import compute_instance_id
from eyenet.contracts.enums import GroupKind, JoinedVia, SourceKind
from eyenet.crypto import load_session_key
from eyenet.identity_pool._provision import provision_identity
from eyenet.storage.factory import get_repository

HERE = pathlib.Path(__file__).resolve().parent


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    p = HERE / ".env"
    if p.exists():
        for raw in p.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


async def _provision(*, dry: bool) -> int:
    env = _load_env()
    name = os.environ.get("PROVISION_NAME", "dc-1")
    data_dir = pathlib.Path(os.environ.get("PROVISION_DATA_DIR", HERE.parents[1] / "data"))
    now = datetime.now(tz=UTC)

    if dry:
        storage = get_repository(in_memory=True)
        data_dir = HERE / "_dry"
        token, cookie, sp = "TOK", "cf_clearance=x", "eyJvcyI6IkxpbnV4In0="
        ua, iid, caps = "Firefox/157", "iid", 1734653
        channel = env.get("DISCORD_CHANNEL_ID", "123")
    else:
        storage = get_repository()  # reads EYENET_* env -> live Postgres
        token = env["DISCORD_TOKEN"]
        cookie = env["DISCORD_COOKIE"]
        sp = env["DISCORD_SUPER_PROPERTIES"]
        ua = env.get("DISCORD_USER_AGENT", "")
        iid = env.get("DISCORD_INSTALLATION_ID", "")
        caps = int(env.get("DISCORD_CAPABILITIES", "1734653"))
        channel = env["DISCORD_CHANNEL_ID"]
    if not token or not cookie or not sp:
        sys.exit("[!] .env missing DISCORD_TOKEN/COOKIE/SUPER_PROPERTIES")

    session_key = load_session_key(data_dir)
    source_id = await storage.upsert_source(
        kind=SourceKind.DISCORD, display_name=f"discord:{name}", created_at=now
    )
    blob = json.dumps({
        "token": token, "cookie": cookie, "super_properties": sp,
        "user_agent": ua, "installation_id": iid, "capabilities": caps,
    }).encode()
    source_config: dict[str, object] = {
        "discord_impersonate": env.get("DISCORD_IMPERSONATE", "firefox147"),
        "discord_user_agent": ua,
        "discord_delay_min": float(env.get("DISCORD_DELAY_MIN", "1.0")),
        "discord_delay_max": float(env.get("DISCORD_DELAY_MAX", "1.5")),
        "discord_enable_waf_bypass": True,
    }
    identity = await provision_identity(
        storage=storage, session_key=session_key, data_dir=data_dir,
        name=name, source_id=source_id, source_kind=SourceKind.DISCORD,
        secret_blob=blob, source_config=source_config,
    )
    print(f"[*] identity provisioned: {name} (source {str(source_id)[:8]})")

    # Collector row (so the collector binds its source + memberships) + one monitored channel.
    username = os.environ.get("PROVISION_USER", "admin")
    user = await storage.get_system_user_by_username(username)
    if user is None:
        print(f"[!] no system_user '{username}'; identity+source done, create the collector "
              "in the UI (or set PROVISION_USER).")
        return 0
    collector = await storage.create_collector(
        instance_name=name, kind=SourceKind.DISCORD, source_id=source_id,
        identity_id=identity.id, config={}, created_at=now, created_by_user_id=user.id,
    )
    group_id, _ = await storage.upsert_group(
        source_id=source_id, platform_groupid=channel,
        kind=GroupKind.CHANNEL, title=None, seen_at=now,
    )
    await storage.open_membership(
        collector_id=collector.id, group_id=group_id, joined_at=now, joined_via=JoinedVia.SEED
    )
    print(f"[*] collector {name} ({compute_instance_id(name, SourceKind.DISCORD)}) "
          f"monitoring channel {channel}")
    print(f"[*] launch: eyenet collector discord --identity {name}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Provision a Discord identity from the poc .env")
    ap.add_argument("--dry", action="store_true", help="in-memory dry run (no secrets, no live DB)")
    sys.exit(asyncio.run(_provision(dry=ap.parse_args().dry)))
