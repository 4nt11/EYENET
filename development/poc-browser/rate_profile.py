#!/usr/bin/env python3
# EXPERIMENT: characterize pwnforums' rate limiter precisely, to set the exact
# per-level timings for the evasion templates (E0..E4).
#
# Phase 0: ensure we start un-throttled (read Retry-After, wait it out).
# Phase 1: from a full bucket, fire back-to-back and count 200s to the first
#          429 -> exact BURST/BUDGET size (+ the Retry-After it hands back).
# Phase 2: after the 429, SILENT-spaced single probes (+30,+60,+120,+180,+300s),
#          capturing status + Retry-After each, to tell the model apart:
#            - a probe returns 200 before +600s  -> leaky bucket (refills early)
#            - Retry-After counts DOWN each probe -> fixed window, timer readable
#            - Retry-After stays ~600 each probe  -> poking RESETS it (stay silent!)
#
# Every line timestamped + flushed for tail -f.
#   python -u rate_profile.py http://<onion>/ warmed.cookies.txt > rate_profile.log 2>&1
from __future__ import annotations

import asyncio
import re
import sys
import time

from playwright.async_api import async_playwright

from browse import PREFS, SOCKS, TB_UA, WEBDRIVER_PATCH, load_netscape

_T0 = time.monotonic()


def log(msg: str = "") -> None:
    print(f"[{time.strftime('%H:%M:%S')} +{time.monotonic() - _T0:7.1f}s] {msg}", flush=True)


async def probe(page, url: str, referer: str):
    """-> (status, retry_after). referer threads a human nav chain."""
    try:
        r = await page.goto(url, wait_until="domcontentloaded", timeout=90_000, referer=referer)
        if r is None:
            return (None, None)
        return (r.status, r.headers.get("retry-after"))
    except Exception as e:  # noqa: BLE001
        return (f"ERR:{type(e).__name__}", None)


async def main(url: str, cookies: str) -> None:
    base = re.sub(r"/+$", "", url)
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True, proxy={"server": SOCKS}, firefox_user_prefs=PREFS)
        ctx = await browser.new_context(
            user_agent=TB_UA, viewport={"width": 1600, "height": 500},
            device_scale_factor=2, timezone_id="Atlantic/Reykjavik",
        )
        await ctx.add_init_script(WEBDRIVER_PATCH)
        await ctx.add_cookies(load_netscape(cookies))
        page = await ctx.new_page()

        st, ra = await probe(page, base + "/", base + "/")
        html = await page.content()
        boards = sorted(set(re.findall(r"(Forum-[A-Za-z0-9-]+)", html)))
        log(f"phase0 index -> {st} RA={ra}, {len(boards)} boards")
        if not boards:
            log("no boards (not logged in / blocked)"); await browser.close(); return

        # Phase 0: wait out any active cooldown so phase 1 starts from a full bucket.
        for _ in range(3):
            st, ra = await probe(page, f"{base}/{boards[0]}", base + "/")
            log(f"phase0 warmup -> {st} RA={ra}")
            if st == 200:
                break
            if st == 429:
                wait = int(ra) + 5 if (ra and ra.isdigit()) else 605
                log(f"phase0 cooling; sleeping {wait}s (silent)")
                await asyncio.sleep(wait)

        # Phase 1: measure the burst/budget.
        log("phase1: bursting ~1s apart to find the budget ...")
        n = 0
        last = f"{base}/{boards[0]}"
        burst = None
        burst_ra = None
        while n < 90:
            slug = boards[n % len(boards)]
            st, ra = await probe(page, f"{base}/{slug}", last)
            last = f"{base}/{slug}"
            n += 1
            log(f"  #{n:3d} {slug[:24]:24} {st}  RA={ra}")
            if st == 429:
                burst, burst_ra = n - 1, ra
                break
            await asyncio.sleep(1.0)
        log(f"phase1 BUDGET = {burst} requests before 429 (Retry-After={burst_ra})")

        # Phase 2: silent-spaced probes to learn the recovery model.
        log("phase2: silent probes to learn the model (watch RA + when 200 returns) ...")
        total_waited = 0
        for delta in (30, 30, 60, 60, 120, 300):
            await asyncio.sleep(delta)
            total_waited += delta
            st, ra = await probe(page, f"{base}/{boards[1]}", base + "/")
            log(f"  +{total_waited:4d}s silent -> {st}  RA={ra}")
            if st == 200:
                log(f"*** CLEARED after ~{total_waited}s of silence "
                    f"({'< 600s -> leaky bucket / short window' if total_waited < 600 else 'full window'}) ***")
                break
        else:
            log("*** never cleared within the probe schedule — long/hard lockout ***")

        await browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: python -u rate_profile.py http://<onion>/ warmed.cookies.txt")
    asyncio.run(main(sys.argv[1], sys.argv[2]))
