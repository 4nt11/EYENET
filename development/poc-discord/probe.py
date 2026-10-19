#!/usr/bin/env python3
"""Discord REST read-probe (PoC).

poc-then-implement: prove we can pull a channel's message chunk as a logged-in USER
without tripping Cloudflare or Discord's self-bot heuristics, and MEASURE the
rate-limit envelope so the real collector's pacing is built from numbers, not guesses.

Run (use the repo venv — it has curl_cffi):
    ../../.venv/bin/python probe.py              # one page: headers + timing + messages
    ../../.venv/bin/python probe.py --limit 50   # bigger chunk (REST max is 100)
    ../../.venv/bin/python probe.py --before <snowflake>   # paginate older (backfill shape)
    ../../.venv/bin/python probe.py --selfcheck  # no network; assert header order only

Why curl_cffi + Firefox impersonation (NOT httpx/requests):
    cf_clearance is bound to the TLS (JA3/JA4) + UA of the browser that minted it.
    httpx/requests send an OpenSSL "Python" ClientHello -> Cloudflare voids the
    clearance -> the account gets flagged. curl_cffi speaks TLS as Firefox so the
    clearance stays valid. firefox147 is curl_cffi's closest target to FF157; for a
    strict wall, pin FF157's exact cipher/sigalg via extra_fp (see README). Same
    tradecraft as eyenet/collectors/forum.

The chunk model (confirms the "works in chunks" hypothesis):
    GET /channels/{id}/messages?limit=<=100[&before=<snowflake>]  -> newest-first page.
    Snowflake cursor (before/after) = the backfill walk; it encodes the timestamp, so
    no now()-substitution recency trap. Live/forward is the Gateway WS (out of scope).
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
API = "https://discord.com/api/v9"

# EXACT header order from the captured Firefox request. Accept-Encoding is deliberately
# OMITTED: with default_headers=False libcurl would not auto-inflate a codec we only
# declared, so we let it negotiate/decode and never hold an undecodable body — the same
# rule as the forum collector's _BASE_HEADERS. Connection is dropped too (illegal on
# HTTP/2+; the browser only shows it in the h1-style capture view).
HEADER_ORDER = [
    "User-Agent",
    "Accept",
    "Accept-Language",
    "Authorization",
    "X-Super-Properties",
    "X-Installation-Id",
    "X-Discord-Locale",
    "X-Discord-Timezone",
    "X-Debug-Options",
    "Alt-Used",
    "Referer",
    "Cookie",
    "Sec-Fetch-Dest",
    "Sec-Fetch-Mode",
    "Sec-Fetch-Site",
    "TE",
]


def load_env(p: pathlib.Path = HERE / ".env") -> dict[str, str]:
    env: dict[str, str] = {}
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def cfg(env: dict[str, str], key: str, default: str = "", required: bool = False) -> str:
    import os

    val = os.environ.get(key) or env.get(key) or default
    if required and not val:
        sys.exit(f"[!] missing {key} — set it in {HERE / '.env'} (copy from env.example)")
    return val


def build_headers(env: dict[str, str]) -> "dict[str, str]":
    ua = cfg(env, "DISCORD_USER_AGENT",
             "Mozilla/5.0 (X11; Linux x86_64; rv:157.0) Gecko/20100101 Firefox/157.0")
    guild = cfg(env, "DISCORD_GUILD_ID") or cfg(env, "DISCORD_CHANNEL_ID", required=True)
    channel = cfg(env, "DISCORD_CHANNEL_ID", required=True)
    values = {
        "User-Agent": ua,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Authorization": cfg(env, "DISCORD_TOKEN", required=True),
        "X-Super-Properties": cfg(env, "DISCORD_SUPER_PROPERTIES", required=True),
        "X-Installation-Id": cfg(env, "DISCORD_INSTALLATION_ID"),
        "X-Discord-Locale": cfg(env, "DISCORD_LOCALE", "en-US"),
        "X-Discord-Timezone": cfg(env, "DISCORD_TIMEZONE", "America/Santiago"),
        "X-Debug-Options": "bugReporterEnabled",
        "Alt-Used": "discord.com",
        "Referer": f"https://discord.com/channels/{guild}/{channel}",
        "Cookie": cfg(env, "DISCORD_COOKIE", required=True),
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "TE": "trailers",
    }
    # Preserve the captured order (dict keeps insertion order).
    return {k: values[k] for k in HEADER_ORDER}


def dump_rate_limits(headers: "dict[str, str]") -> None:
    keys = [k for k in headers
            if k.lower().startswith(("x-ratelimit", "retry-after", "cf-", "via", "x-discord"))]
    print("  rate-limit / edge headers:")
    for k in sorted(keys):
        print(f"    {k}: {headers[k]}")
    if not keys:
        print("    (none returned)")


def run(limit: int, before: str | None) -> int:
    env = load_env()
    try:
        from curl_cffi import requests
    except ImportError:
        sys.exit("[!] curl_cffi missing — run with the repo venv: ../../.venv/bin/python probe.py")

    impersonate = cfg(env, "DISCORD_IMPERSONATE", "firefox147")
    headers = build_headers(env)
    channel = cfg(env, "DISCORD_CHANNEL_ID", required=True)
    url = f"{API}/channels/{channel}/messages?limit={limit}" + (f"&before={before}" if before else "")

    print(f"[*] GET {url}")
    print(f"[*] impersonate={impersonate}  (user token, {len(headers)} headers, order-preserved)")
    t0 = time.monotonic()
    # default_headers=False: send ONLY our ordered header set; TLS/HTTP2 fingerprint
    # still comes from impersonate. ponytail: no retry/backoff here — this is a probe,
    # the real collector gets paced retries driven by the headers we're measuring.
    r = requests.get(url, headers=headers, impersonate=impersonate,
                     default_headers=False, timeout=30)
    dt = (time.monotonic() - t0) * 1000.0

    print(f"[*] HTTP {r.status_code}  in {dt:.0f} ms")
    dump_rate_limits(dict(r.headers))

    if r.status_code == 401:
        sys.exit("[!] 401 — token missing/expired. Refill DISCORD_TOKEN.")
    if r.status_code == 403:
        sys.exit("[!] 403 — likely Cloudflare challenge / stale cf_clearance. "
                 "Remint via FlareSolverr (see README) and refill DISCORD_COOKIE.")
    if r.status_code == 429:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        sys.exit(f"[!] 429 rate-limited. retry_after={body.get('retry_after')} "
                 f"global={body.get('global')} scope={r.headers.get('x-ratelimit-scope')}")
    if r.status_code != 200:
        sys.exit(f"[!] unexpected {r.status_code}: {r.text[:300]}")

    data = r.json()
    print(f"\n[*] {len(data)} messages (newest first):")
    for m in data:
        a = m.get("author", {})
        who = a.get("username") or a.get("global_name") or a.get("id", "?")
        if a.get("bot"):
            who += "*"  # bot author
        body = " ".join((m.get("content") or "").split())
        flags = []
        if m.get("referenced_message"):
            flags.append("reply")
        tag = f" [{','.join(flags)}]" if flags else ""
        print(f"  {m.get('timestamp', '')[:19]}  @{who:<20} (t{m.get('type')}) "
              f"{body[:90]}{tag}")
        # Bots / drop-bots carry the real payload in embeds, not content — surface it.
        for e in m.get("embeds", []):
            parts = [p for p in (e.get("title"), e.get("description")) if p]
            line = " | ".join(" ".join(p.split()) for p in parts)
            if e.get("url"):
                line += f"  <{e['url']}>"
            print(f"      embed: {line[:160]}")
            for f in e.get("fields", []):
                print(f"        - {f.get('name','')}: {' '.join((f.get('value') or '').split())[:100]}")
        for at in m.get("attachments", []):
            print(f"      attach: {at.get('filename','?')}  {at.get('url','')}")
    if data:
        print(f"\n[*] oldest id in page = {data[-1]['id']}  "
              f"(pass as --before to walk older)")
    return 0


def backfill(limit: int, delay: float, max_pages: int) -> int:
    """Walk history UPWARD (newest -> oldest via before-cursor), the natural scroll-up.
    NEVER after=0 / genesis-first (see DESIGN.md + the read-upward memory)."""
    env = load_env()
    try:
        from curl_cffi import requests
    except ImportError:
        sys.exit("[!] curl_cffi missing — use the repo venv: ../../.venv/bin/python probe.py")
    impersonate = cfg(env, "DISCORD_IMPERSONATE", "firefox147")
    headers = build_headers(env)
    channel = cfg(env, "DISCORD_CHANNEL_ID", required=True)
    print(f"[*] backfill channel {channel}  limit={limit} delay={delay}s "
          f"max_pages={max_pages or '∞'}  impersonate={impersonate}")

    before: str | None = None
    pages = total = 0
    authors: set[str] = set()
    newest_ts = oldest_ts = None
    times: list[float] = []
    while max_pages == 0 or pages < max_pages:
        url = f"{API}/channels/{channel}/messages?limit={limit}" + (f"&before={before}" if before else "")
        t0 = time.monotonic()
        r = requests.get(url, headers=headers, impersonate=impersonate,
                         default_headers=False, timeout=30)
        dt = (time.monotonic() - t0) * 1000.0
        times.append(dt)
        if r.status_code == 429:
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            print(f"[!] 429 after {pages} pages — retry_after={body.get('retry_after')} "
                  f"scope={r.headers.get('x-ratelimit-scope')}. HARD STOP.")
            break
        if r.status_code != 200:
            print(f"[!] HTTP {r.status_code} after {pages} pages: {r.text[:160]}")
            break
        data = r.json()
        if not data:
            print(f"  page {pages + 1}: 0 msgs — reached channel start")
            break
        pages += 1
        total += len(data)
        page_new, page_old = data[0].get("timestamp", "")[:19], data[-1].get("timestamp", "")[:19]
        newest_ts = newest_ts or page_new
        oldest_ts = page_old
        for m in data:
            a = m.get("author", {})
            authors.add(a.get("username") or a.get("id", ""))
        print(f"  page {pages:>2}: {len(data):>3} msgs  {page_old} .. {page_new}  "
              f"({dt:.0f}ms)  before={before or 'newest'}")
        before = data[-1]["id"]
        if len(data) < limit:
            print("  (short page -> reached channel start)")
            break
        time.sleep(delay)

    avg = sum(times) / len(times) if times else 0.0
    print(f"\n[*] {total} msgs across {pages} pages | span {oldest_ts} .. {newest_ts} | "
          f"{len(authors)} authors | avg {avg:.0f}ms/req")
    return 0


def selfcheck() -> int:
    # No network: prove header construction + order are stable.
    env = {k: "x" for k in (
        "DISCORD_TOKEN", "DISCORD_COOKIE", "DISCORD_SUPER_PROPERTIES",
        "DISCORD_INSTALLATION_ID", "DISCORD_CHANNEL_ID", "DISCORD_GUILD_ID")}
    h = build_headers(env)
    assert list(h.keys()) == HEADER_ORDER, f"header order drift: {list(h.keys())}"
    assert "Accept-Encoding" not in h, "Accept-Encoding must stay omitted (decode trap)"
    assert "Connection" not in h, "Connection is illegal on HTTP/2+"
    assert h["Authorization"] and h["Cookie"], "secrets not wired"
    print(f"[ok] selfcheck passed — {len(h)} headers in captured order, no decode/h2 traps")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Discord REST read-probe (PoC)")
    ap.add_argument("--limit", type=int, default=10, help="messages per page (REST max 100)")
    ap.add_argument("--before", help="snowflake cursor: fetch messages older than this id")
    ap.add_argument("--channel", help="override DISCORD_CHANNEL_ID for this run")
    ap.add_argument("--guild", help="override DISCORD_GUILD_ID (keeps the Referer honest)")
    ap.add_argument("--backfill", action="store_true", help="walk history upward (before-cursor)")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between backfill requests")
    ap.add_argument("--max-pages", type=int, default=0, help="stop after N pages (0 = until channel start)")
    ap.add_argument("--selfcheck", action="store_true", help="validate headers offline, no request")
    args = ap.parse_args()
    import os
    if args.channel:
        os.environ["DISCORD_CHANNEL_ID"] = args.channel
    if args.guild:
        os.environ["DISCORD_GUILD_ID"] = args.guild
    if args.selfcheck:
        sys.exit(selfcheck())
    if args.backfill:
        sys.exit(backfill(args.limit, args.delay, args.max_pages))
    sys.exit(run(args.limit, args.before))
