#!/usr/bin/env python3
# EXPERIMENT: does clean-session category enumeration still trip pf-auto?
#
# The banned account had TWO sins: clearnet->Tor IP jump AND bulk board
# enumeration. This throwaway has a clean Tor-native session + matched
# fingerprint, so if it still bans here, the ENUMERATION BEHAVIOUR alone is the
# trigger (and we learn the threshold: how many requests / how fast). If it
# survives, the IP-jump was the whole story and pacing is a softer constraint.
#
#   python enum_experiment.py http://<onion>/ warmed.cookies.txt
from __future__ import annotations

import asyncio
import random
import re
import sys
import time

from playwright.async_api import async_playwright

from browse import PREFS, SOCKS, TB_UA, WEBDRIVER_PATCH, classify, load_netscape

DURATION = 300  # 5 minutes
DELAY = (1.0, 3.0)  # brisk human clicking — "let it rip" to probe the threshold fast


async def main(url: str, cookies: str) -> None:
    base = re.sub(r"/+$", "", url)
    t0 = time.monotonic()

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True, proxy={"server": SOCKS}, firefox_user_prefs=PREFS)
        ctx = await browser.new_context(
            user_agent=TB_UA, viewport={"width": 1600, "height": 500},
            device_scale_factor=2, timezone_id="Atlantic/Reykjavik",
        )
        await ctx.add_init_script(WEBDRIVER_PATCH)
        await ctx.add_cookies(load_netscape(cookies))
        page = await ctx.new_page()

        r = await page.goto(base + "/", wait_until="domcontentloaded", timeout=120_000)
        html = await page.content()
        cls = classify(html)
        logged_in = "logout" in html.lower() or "usercp" in html.lower()
        print(f"[{time.monotonic() - t0:6.1f}s] #0 index HTTP {r.status if r else '?'} {cls} logged_in={logged_in}")
        if cls == "BANNED":
            print("already banned at index — nothing to test"); await browser.close(); return

        boards = sorted(set(re.findall(r"(Forum-[A-Za-z0-9-]+)", html)))
        print(f"enumerating {len(boards)} boards, up to {DURATION}s @ {DELAY[0]}-{DELAY[1]}s spacing ...")
        last = base + "/"
        req = 0
        while time.monotonic() - t0 < DURATION and boards:
            slug = boards[req % len(boards)]
            req += 1
            u = f"{base}/{slug}"
            try:
                r = await page.goto(u, wait_until="domcontentloaded", timeout=90_000, referer=last)
            except Exception as e:  # noqa: BLE001 - log + continue; a slow circuit isn't the signal
                print(f"[{time.monotonic() - t0:6.1f}s] #{req} {slug[:28]:28} ERR {type(e).__name__}")
                await asyncio.sleep(random.uniform(*DELAY))  # noqa: S311
                continue
            html = await page.content()
            cls = classify(html)
            print(f"[{time.monotonic() - t0:6.1f}s] #{req} {slug[:28]:28} HTTP {r.status if r else '?'} {cls}")
            if cls in ("BANNED", "CHALLENGE"):
                print(f"\n*** {cls} after {req} enumeration requests / {time.monotonic() - t0:.0f}s ***")
                await browser.close()
                return
            last = u
            await asyncio.sleep(random.uniform(*DELAY))  # noqa: S311

        print(f"\n*** SURVIVED {req} requests over {int(time.monotonic() - t0)}s with NO ban/challenge ***")
        print("    -> clean session tolerates enumeration; the IP-jump was the ban, not the crawl.")
        await browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: python enum_experiment.py http://<onion>/ warmed.cookies.txt")
    asyncio.run(main(sys.argv[1], sys.argv[2]))
