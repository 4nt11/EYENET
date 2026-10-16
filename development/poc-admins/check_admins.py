#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""POC: pull a Telegram channel's admin list and diff it against the OG Rutify
roster, to answer the one hard question the message backfill could not:

    is any @RutifyTeam admin the SAME Telegram account as an OG Rutify member?

Runs INSIDE the collector container (docker-supervisor-1) so it can reuse the
encrypted `tgtesting` session instead of opening a second TG login. It decrypts
the Fernet session blob into an in-memory StringSession exactly the way the live
collector does (eyenet.crypto + the identity pool), connects read-only, and asks
for the channel admins via ChannelParticipantsAdmins.

PAUSE THE COLLECTOR FIRST. Two clients on the same auth_key concurrently can trip
AUTH_KEY_DUPLICATED and Telegram may drop one connection.

Run:
    docker cp rutify-users.json docker-supervisor-1:/tmp/rutify-users.json
    docker cp development/poc-admins/check_admins.py docker-supervisor-1:/tmp/check_admins.py
    docker exec -it docker-supervisor-1 python3 /tmp/check_admins.py --roster /tmp/rutify-users.json

Self-check (no telethon, no network):
    python3 check_admins.py --self-test
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path


def load_roster_ids(roster_path: Path) -> dict[int, dict]:
    """Map OG Telegram user-id -> roster entry, across users + admins + bots."""
    data = json.loads(roster_path.read_text(encoding="utf-8"))
    out: dict[int, dict] = {}
    for bucket in ("users", "admins", "bots"):
        for e in data.get(bucket, []):
            uid = e.get("id")
            if isinstance(uid, int):
                out.setdefault(uid, {**e, "_bucket": bucket})
    return out


def diff_admins(admins: list[dict], roster: dict[int, dict]) -> list[dict]:
    """Annotate each admin with whether its id is in the OG roster.

    `admins`: [{id, username, name}], `roster`: id -> entry. The id match is the
    strong signal (same account); username match is reported separately upstream
    because handles can be reused across accounts.
    """
    rows = []
    for a in admins:
        hit = roster.get(a["id"])
        rows.append({**a, "overlap": hit is not None, "og_entry": hit})
    return rows


def _read_identity(data_dir: Path, name: str) -> tuple[str, int, str]:
    """Return (session_path, api_id, api_hash) for the telegram identity `name`.

    Reads the pool row straight from the operating DB (read-only) rather than
    booting the async storage layer. api_hash stays in-process; it is never
    printed.
    """
    con = sqlite3.connect(f"file:{data_dir / 'main.db'}?mode=ro", uri=True, timeout=5)
    try:
        row = con.execute(
            "select session_path, source_config from identity where name=?", (name,)
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise SystemExit(f"identity {name!r} not found in {data_dir / 'main.db'}")
    session_path, source_config = row
    cfg = json.loads(source_config) if source_config else {}
    api_id = cfg.get("telegram_api_id")
    api_hash = cfg.get("telegram_api_hash")
    if not session_path or api_id is None or api_hash is None:
        raise SystemExit(f"identity {name!r} is not a usable telegram identity")
    return session_path, int(api_id), str(api_hash)


async def fetch_admins(data_dir: Path, identity: str, channel: str) -> list[dict]:
    # Imported lazily so --self-test runs without telethon / eyenet installed.
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.tl.types import ChannelParticipantsAdmins

    from eyenet.crypto import decrypt_session, load_session_key

    session_path, api_id, api_hash = _read_identity(data_dir, identity)
    key = load_session_key(data_dir)
    plaintext = decrypt_session(key, Path(session_path).read_bytes())

    client = TelegramClient(StringSession(plaintext), api_id, api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise SystemExit("session is not authorized — wrong identity or stale blob")
        parts = await client.get_participants(
            channel, filter=ChannelParticipantsAdmins()
        )
    finally:
        await client.disconnect()

    admins = []
    for u in parts:
        name = " ".join(x for x in (u.first_name, u.last_name) if x) or None
        admins.append({"id": u.id, "username": u.username, "name": name})
    return admins


def report(admins: list[dict], roster: dict[int, dict]) -> int:
    rows = diff_admins(admins, roster)
    print(f"\n@channel admins: {len(rows)}")
    for r in rows:
        tag = "  <-- OVERLAP" if r["overlap"] else ""
        print(f"  id={r['id']:<14} @{r['username'] or '':<18} {r['name'] or '':<22}{tag}")
        if r["overlap"]:
            og = r["og_entry"]
            print(
                f"       OG roster [{og['_bucket']}]: @{og.get('username') or ''} "
                f"first={og.get('first_name')!r} last={og.get('last_name')!r}"
            )

    # Secondary, weaker: handle reuse without an id match.
    og_handles = {
        (e.get("username") or "").lower(): uid
        for uid, e in roster.items()
        if e.get("username")
    }
    handle_hits = [
        a
        for a in admins
        if a["username"]
        and a["username"].lower() in og_handles
        and og_handles[a["username"].lower()] != a["id"]
    ]

    id_hits = [r for r in rows if r["overlap"]]
    print("\n=== VERDICT ===")
    if id_hits:
        print(f"HARD LINK: {len(id_hits)} admin id(s) also in the OG Rutify roster.")
        print("Same Telegram account(s). The imposter is operated by an OG member.")
    else:
        print("NO id overlap. No @RutifyTeam admin is an OG Rutify account.")
        print("Consistent with the different-operator read (brand-squat, not insider).")
    if handle_hits:
        print(
            f"NOTE: {len(handle_hits)} handle match(es) with a DIFFERENT id "
            "(reused username, weaker signal): "
            + ", ".join(f"@{a['username']}" for a in handle_hits)
        )
    return 0


def self_test() -> int:
    roster = {
        111: {"id": 111, "username": "igna", "first_name": "igna", "_bucket": "admins"},
        222: {"id": 222, "username": "rossy", "first_name": "Rossy", "_bucket": "users"},
    }
    # 111 = id overlap; 999 = clean miss; 222-handle on a new id = handle-only.
    admins = [
        {"id": 111, "username": "whatever", "name": "x"},
        {"id": 999, "username": "roberto", "name": "Roberto"},
    ]
    rows = diff_admins(admins, roster)
    assert rows[0]["overlap"] is True, "id 111 must overlap"
    assert rows[1]["overlap"] is False, "id 999 must not overlap"
    assert diff_admins([], roster) == [], "empty admin list -> empty diff"
    # handle-only reuse: same username, different id -> not an id overlap
    handle_only = diff_admins([{"id": 777, "username": "igna", "name": None}], roster)
    assert handle_only[0]["overlap"] is False, "handle reuse is not an id match"
    print("self-test OK")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", type=Path, default=Path("/var/lib/eyenet"))
    p.add_argument("--identity", default="tgtesting")
    p.add_argument("--channel", default="@RutifyTeam")
    p.add_argument("--roster", type=Path, default=Path("/tmp/rutify-users.json"))
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()

    if args.self_test:
        return self_test()

    roster = load_roster_ids(args.roster)
    print(f"OG roster ids loaded: {len(roster)}")
    admins = asyncio.run(fetch_admins(args.data_dir, args.identity, args.channel))
    return report(admins, roster)


if __name__ == "__main__":
    sys.exit(main())
