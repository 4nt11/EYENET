#!/usr/bin/env python3
"""Discord Gateway discovery PoC (native path).

Connects the real-client way and reads the topology out of READY — no REST
/users/@me/guilds or /guilds/{id}/channels (those are bot/OAuth-flavored; the client
never calls them). See DESIGN.md "Discovery — Gateway (WS)".

Native, per ANTI:
  - curl_cffi impersonated WebSocket (same browser fingerprint as the REST probe).
  - connect with compress=zlib-stream and inflate the CONTINUOUS server stream with a
    single zlib.decompressobj (messages end at the 00 00 ff ff flush). No no-compress
    shortcut.
  - IDENTIFY mirrors the captured Chrome-154 client frame; fresh launch ids per connect,
    stable installation_id; emit the proprietary op 41 init right after, like the client.

UNIFY the browser: capture was Chrome 154, so impersonate chrome150 here AND switch the
REST probe to the same Chrome session (token/cookie/super-props). Firefox-REST +
Chrome-WS on one account is a flag.

Run (repo venv):
    ../../.venv/bin/python gateway.py             # connect, identify, print guild/channel tree
    ../../.venv/bin/python gateway.py --selfcheck # offline: build+validate IDENTIFY only

.env must be the SAME browser session: DISCORD_TOKEN, DISCORD_COOKIE,
DISCORD_INSTALLATION_ID (+ optional DISCORD_IMPERSONATE, default chrome150).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
import threading
import time
import uuid
import zlib

import probe  # reuse load_env/cfg from the REST probe (same dir)

GATEWAY_URL = "wss://gateway.discord.gg/?encoding=json&v=9&compress=zlib-stream"
ZLIB_SUFFIX = b"\x00\x00\xff\xff"

# Captured Chrome-154 client fingerprint (non-secret; override via .env if the build moves).
CAPABILITIES = 1734653
BUILD_NUMBER = 641004
UA_CHROME = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")
QOS_TOKEN = "CgIIAQ=="


def build_identify(env: dict[str, str]) -> dict:
    # Fresh launch identity per connect (a real relaunch); stable installation_id.
    return {
        "op": 2,
        "d": {
            "token": probe.cfg(env, "DISCORD_TOKEN", required=True),
            "capabilities": CAPABILITIES,
            "properties": {
                "os": "Linux",
                "browser": "Chrome",
                "device": "",
                "device_model_name": "",
                "system_locale": probe.cfg(env, "DISCORD_LOCALE", "en-US"),
                "has_client_mods": False,
                "browser_user_agent": probe.cfg(env, "DISCORD_USER_AGENT", UA_CHROME),
                "browser_version": "154.0.0.0",
                "os_version": "",
                "referrer": "",
                "referring_domain": "",
                "referrer_current": "https://discord.com/",
                "referring_domain_current": "discord.com",
                "release_channel": "stable",
                "client_build_number": int(probe.cfg(env, "DISCORD_BUILD_NUMBER", str(BUILD_NUMBER))),
                "client_event_source": None,
                "client_launch_id": str(uuid.uuid4()),
                "launch_signature": str(uuid.uuid4()),
                "client_app_state": "focused",
                "is_fast_connect": False,
                "gateway_connect_reasons": "AppSkeleton",
                "installation_id": probe.cfg(env, "DISCORD_INSTALLATION_ID", required=True),
            },
            "presence": {"status": "unknown", "since": 0, "activities": [], "afk": False},
            "compress": False,
            "client_state": {"guild_versions": {}},
            "qos_token": QOS_TOKEN,
        },
    }


class StreamInflator:
    """Single continuous zlib context for the whole socket (zlib-stream)."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._dec = zlib.decompressobj()

    def feed(self, chunk: bytes) -> str | None:
        # A gateway message is complete when the raw stream hits the ZLIB_SYNC flush.
        self._buf.extend(chunk)
        if not self._buf.endswith(ZLIB_SUFFIX):
            return None
        out = self._dec.decompress(bytes(self._buf))
        self._buf.clear()
        return out.decode("utf-8")


def run(channel_filter: str | None = None, resolve_roles: str | None = None) -> int:
    env = probe.load_env()
    from curl_cffi import requests

    impersonate = probe.cfg(env, "DISCORD_IMPERSONATE", "chrome150")
    cookie = probe.cfg(env, "DISCORD_COOKIE", required=True)
    headers = {
        "User-Agent": probe.cfg(env, "DISCORD_USER_AGENT", UA_CHROME),
        "Origin": "https://discord.com",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": cookie,
    }

    print(f"[*] ws_connect {GATEWAY_URL}  impersonate={impersonate}")
    sess = requests.Session(impersonate=impersonate)
    ws = sess.ws_connect(GATEWAY_URL, headers=headers)
    inflator = StreamInflator()
    last_seq: int | None = None
    hb_interval = 41.25
    stop = threading.Event()

    def recv_msg() -> dict | None:
        # curl_cffi recv() returns bytes or (bytes, frame); normalize, then inflate.
        while not stop.is_set():
            raw = ws.recv()
            if isinstance(raw, tuple):
                raw = raw[0]
            if not raw:
                continue
            text = inflator.feed(raw)
            if text is not None:
                return json.loads(text)
        return None

    def heartbeat() -> None:
        # jittered, native cadence; keeps the socket alive if READY is slow
        time.sleep(hb_interval * random.uniform(0.85, 1.0))
        while not stop.is_set():
            try:
                ws.send(json.dumps({"op": 1, "d": last_seq}))
            except Exception:
                return
            time.sleep(hb_interval * random.uniform(0.9, 1.0))

    # 1) HELLO
    hello = recv_msg()
    if not hello or hello.get("op") != 10:
        sys.exit(f"[!] expected HELLO op10, got {hello and hello.get('op')}")
    hb_interval = hello["d"]["heartbeat_interval"] / 1000.0
    print(f"[*] HELLO  heartbeat_interval={hb_interval:.2f}s")
    threading.Thread(target=heartbeat, daemon=True).start()

    # 2) IDENTIFY (+ the proprietary op41 init the client sends right after)
    ws.send(json.dumps(build_identify(env)))
    ws.send(json.dumps({"op": 41, "d": {
        "initialization_timestamp": int(time.time() * 1000),
        "session_id": str(uuid.uuid4()),
        "client_launch_id": str(uuid.uuid4()),
    }}))
    print("[*] sent IDENTIFY + op41 init")

    # 3) read until READY, then dump the discovered tree
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        msg = recv_msg()
        if msg is None:
            break
        if msg.get("s") is not None:
            last_seq = msg["s"]
        op, t = msg.get("op"), msg.get("t")
        if op == 0 and t == "READY":
            d = msg["d"]
            guilds = d.get("guilds", [])
            user = d.get("user", {})
            print(f"\n[*] READY  user=@{user.get('username')}  session={d.get('session_id')}")
            print(f"[*] {len(guilds)} guilds, {len(d.get('private_channels', []))} DMs")
            ctype = {0: "text", 2: "voice", 4: "category", 5: "announce", 13: "stage",
                     15: "forum", 11: "pub-thread", 12: "priv-thread"}
            gname = lambda g: g.get("properties", {}).get("name", g.get("name", ""))
            if channel_filter:
                # Find the guild that owns this channel, print its FULL channel map
                # (names only live here in READY, never in the REST message fetch).
                for g in guilds:
                    chans = g.get("channels", [])
                    if any(str(c.get("id")) == str(channel_filter) for c in chans):
                        print(f"\n[*] guild {g.get('id')}  {gname(g)}  ({len(chans)} channels)")
                        for c in sorted(chans, key=lambda c: (c.get("parent_id") or "", c.get("position", 0))):
                            mark = "  <== TARGET" if str(c.get("id")) == str(channel_filter) else ""
                            print(f"    {ctype.get(c.get('type'), c.get('type')):<11} "
                                  f"{(c.get('name') or '(none)'):<30} id={c.get('id')} "
                                  f"parent={c.get('parent_id')}{mark}")
                        # Role DEFINITIONS live here in READY — a member's roles:[ids]
                        # is meaningless without this id->name/color/position table.
                        roles = g.get("roles", [])
                        want = {x for x in (resolve_roles or "").split(",") if x}
                        print(f"\n[*] {len(roles)} roles (higher position = more senior):")
                        for r in sorted(roles, key=lambda r: -r.get("position", 0)):
                            mark = "  <== has this" if str(r.get("id")) in want else ""
                            col = f"#{r.get('color', 0):06x}" if r.get("color") else "-"
                            perms = r.get("permissions", "")
                            print(f"    pos {r.get('position', 0):>3}  {(r.get('name') or '?'):<22} "
                                  f"id={r.get('id')} color={col} perms={perms}{mark}")
                        break
                else:
                    print(f"[!] channel {channel_filter} not in any guild's READY channels")
            else:
                for g in guilds:
                    chans = g.get("channels", [])
                    print(f"  guild {g.get('id')}  {gname(g)}  ({len(chans)} channels)")
                    for c in chans:
                        if c.get("type") in (0, 5, 15):
                            print(f"      #{c.get('name','?'):<28} id={c.get('id')} "
                                  f"type={c.get('type')} parent={c.get('parent_id')}")
            stop.set()
            try:
                ws.close()
            except Exception:
                pass
            return 0
        if t:
            print(f"    dispatch {t} (s={msg.get('s')})")
    stop.set()
    print("[!] no READY within 30s")
    return 1


def selfcheck() -> int:
    env = {k: "x" for k in ("DISCORD_TOKEN", "DISCORD_INSTALLATION_ID")}
    f = build_identify(env)
    d = f["d"]
    assert f["op"] == 2
    assert d["capabilities"] == CAPABILITIES
    for k in ("os", "browser", "browser_user_agent", "client_build_number",
              "client_launch_id", "launch_signature", "installation_id"):
        assert k in d["properties"], f"missing properties.{k}"
    assert d["compress"] is False and d["client_state"] == {"guild_versions": {}}
    # fresh launch ids each build
    assert build_identify(env)["d"]["properties"]["client_launch_id"] != \
        d["properties"]["client_launch_id"], "launch id must be fresh per connect"
    probe.selfcheck()  # also validate the REST header set
    print("[ok] gateway selfcheck passed — IDENTIFY shape + fresh launch id")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Discord Gateway discovery PoC")
    ap.add_argument("--channel", help="after READY, print the full channel map of the guild owning this channel id")
    ap.add_argument("--roles", help="comma-separated role ids to flag in that guild's role table")
    ap.add_argument("--selfcheck", action="store_true", help="offline: validate IDENTIFY only")
    args = ap.parse_args()
    sys.exit(selfcheck() if args.selfcheck else run(args.channel, args.roles))
