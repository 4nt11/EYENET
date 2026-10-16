#!/usr/bin/env python3
# EXPERIMENT: does a fresh Tor circuit reset pwnforums' nginx 429 budget?
#
# Onion services have no exit node; nginx behind one typically sees 127.0.0.1
# for everyone, so per-client limit_req must key on a per-circuit ID
# (HiddenServiceExportCircuitID). If so, a NEW circuit == a fresh 60-req budget.
#
# We force distinct circuits with Tor SOCKS-auth isolation (IsolateSOCKSAuth is
# on by default): a different SOCKS user/pass => a different circuit. Two circuits
# run concurrently with the SAME account cookies:
#   A: enumerate until 429 (throttled), confirm still 429 on the same circuit.
#   B: one request on a fresh circuit. 200 => per-circuit key (rotation wins).
#                                      429 => cookie/account/global key (useless).
#
# Every line is timestamped (wall-clock + seconds since start) and flushed, so
# `tail -f circuit_rotation.log` tracks it live.
#
#   python -u circuit_rotation.py http://<onion>/ warmed.cookies.txt > circuit_rotation.log 2>&1
from __future__ import annotations

import asyncio
import re
import sys
import time

from playwright.async_api import async_playwright

from browse import PREFS, TB_UA, WEBDRIVER_PATCH, load_netscape

# Playwright-Firefox can't do SOCKS5 auth, so we isolate circuits with TWO tor
# instances instead: 9050 (circuit A) and 9052 (circuit B). Separate daemons =
# guaranteed-distinct circuits to the onion.
SOCKS_A = "socks5://127.0.0.1:9050"
SOCKS_B = "socks5://127.0.0.1:9052"

_T0 = time.monotonic()


def log(msg: str = "") -> None:
    el = time.monotonic() - _T0
    print(f"[{time.strftime('%H:%M:%S')} +{el:7.1f}s] {msg}", flush=True)


async def make(p, socks_server: str, cookies: str):
    """A browser bound to a distinct Tor instance (= distinct circuit)."""
    browser = await p.firefox.launch(
        headless=True,
        proxy={"server": socks_server},
        firefox_user_prefs=PREFS,
    )
    ctx = await browser.new_context(
        user_agent=TB_UA, viewport={"width": 1600, "height": 500},
        device_scale_factor=2, timezone_id="Atlantic/Reykjavik",
    )
    await ctx.add_init_script(WEBDRIVER_PATCH)
    await ctx.add_cookies(load_netscape(cookies))
    page = await ctx.new_page()
    return browser, page


async def get(page, url: str, referer: str):
    try:
        r = await page.goto(url, wait_until="domcontentloaded", timeout=90_000, referer=referer)
        return r.status if r else None
    except Exception as e:  # noqa: BLE001
        return f"ERR:{type(e).__name__}"


async def main(url: str, cookies: str) -> None:
    base = re.sub(r"/+$", "", url)
    async with async_playwright() as p:
        log(f"building circuit A ({SOCKS_A}) + circuit B ({SOCKS_B}) ...")
        bA, pA = await make(p, SOCKS_A, cookies)
        bB, pB = await make(p, SOCKS_B, cookies)

        sA = await get(pA, base + "/", base + "/")
        html = await pA.content()
        boards = sorted(set(re.findall(r"(Forum-[A-Za-z0-9-]+)", html)))
        log(f"[A] index HTTP {sA}, {len(boards)} boards; enumerating until 429 ...")
        if not boards:
            log("no boards (not logged in / already blocked)"); await bA.close(); await bB.close(); return

        hit = None
        last = base + "/"
        for i in range(85):
            slug = boards[i % len(boards)]
            u = f"{base}/{slug}"
            st = await get(pA, u, last)
            last = u
            log(f"  [A] #{i + 1:3d} {slug[:26]:26} {st}")
            if st == 429:
                hit = i + 1
                break
            await asyncio.sleep(0.4)

        log("[A] confirming same circuit is still throttled ...")
        a_again = await get(pA, f"{base}/{boards[0]}", last)
        log(f"  [A] same-circuit retry -> {a_again}")

        log("[B] firing ONE request on the FRESH circuit (same cookies) ...")
        b_fresh = await get(pB, f"{base}/{boards[1]}", base + "/")
        log(f"  [B] fresh-circuit request -> {b_fresh}")

        log("")
        log(f"RESULT: A tripped 429 at request #{hit} | A-again={a_again} | B-fresh={b_fresh}")
        if a_again == 429 and b_fresh == 200:
            log("*** ROTATION WINS: limit_req is keyed PER TOR CIRCUIT. A fresh circuit = a fresh")
            log("    ~60-req budget. Rotate circuits per window and throughput scales with circuits. ***")
        elif b_fresh == 429:
            log("*** ROTATION USELESS: budget shared across circuits (keyed on session cookie or")
            log("    global). Pacing + honoring Retry-After is the only lever. ***")
        else:
            log(f"inconclusive (a_again={a_again}, b_fresh={b_fresh}) — check isolation / cooldown")
        await bA.close()
        await bB.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: python -u circuit_rotation.py http://<onion>/ warmed.cookies.txt")
    asyncio.run(main(sys.argv[1], sys.argv[2]))
