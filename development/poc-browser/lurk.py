#!/usr/bin/env python3
# ENDURANCE: a well-behaved lurker that COLLECTS without ever pinging the limiter.
# E1 pacing (15-40s jittered), capped at COUNT threads (a quarter of the ~60
# budget), extracting title + post-count per thread (page 1 = OP + first posts)
# to prove collection. Hard ABORT on any 429 — never hammer, never escalate.
# This is the non-abusive experiment: does a ghost collect cleanly over a stretch?
#
#   python -u lurk.py http://<onion>/ warmed.cookies.txt [Forum-Slug] > lurk.log 2>&1
from __future__ import annotations

import asyncio
import random
import re
import sys
import time

from playwright.async_api import async_playwright

from browse import PREFS, SOCKS, TB_UA, WEBDRIVER_PATCH, classify, load_netscape

DELAY = (15.0, 40.0)  # E1 inter-request spacing
COUNT = 15            # threads to read — a quarter of the ~60 budget
_T0 = time.monotonic()


def log(m: str = "") -> None:
    print(f"[{time.strftime('%H:%M:%S')} +{time.monotonic() - _T0:6.1f}s] {m}", flush=True)


def posts_in(html: str) -> int:
    return len(set(re.findall(r'id="post_(\d+)"', html)))  # MyBB post markers


def title_of(html: str) -> str:
    m = re.search(r"<title[^>]*>([^<]*)</title>", html, re.I)
    return (m.group(1).strip() if m else "")


async def main(url: str, cookies: str, board: str | None) -> None:
    base = re.sub(r"/+$", "", url)
    async with async_playwright() as p:
        b = await p.firefox.launch(headless=True, proxy={"server": SOCKS}, firefox_user_prefs=PREFS)
        ctx = await b.new_context(
            user_agent=TB_UA, viewport={"width": 1600, "height": 500},
            device_scale_factor=2, timezone_id="Atlantic/Reykjavik",
        )
        await ctx.add_init_script(WEBDRIVER_PATCH)
        await ctx.add_cookies(load_netscape(cookies))
        page = await ctx.new_page()

        r = await page.goto(base + "/", wait_until="domcontentloaded", timeout=120_000)
        idx = await page.content()
        log(f"index [{r.status if r else '?'}] {classify(idx)}")
        if classify(idx) != "FORUM-OK":
            log("not a clean logged-in index — aborting"); await b.close(); return

        if not board:
            pref = re.findall(r"(Forum-Databases|Forum-Leaks|Forum-Stealer-Logs|Forum-Cracked-Accounts)", idx)
            board = pref[0] if pref else (re.findall(r"(Forum-[A-Za-z0-9-]+)", idx) or ["Forum-General"])[0]

        d = random.uniform(*DELAY)  # noqa: S311
        log(f"target board: {board} (dwell {d:.0f}s before opening)")
        await asyncio.sleep(d)
        r = await page.goto(f"{base}/{board}", wait_until="domcontentloaded", timeout=90_000, referer=base + "/")
        bh = await page.content()
        log(f"board {board} [{r.status if r else '?'}] {classify(bh)}")
        if r and r.status == 429:
            log("429 on board — going silent, aborting"); await b.close(); return

        seen: set[str] = set()
        threads: list[str] = []
        for m in re.findall(r"(Thread-[A-Za-z0-9%._-]+)", bh):
            c = m.split("?")[0]
            if c not in seen:
                seen.add(c)
                threads.append(c)
        log(f"{len(threads)} thread links; reading up to {COUNT} at E1 pace ...")

        visited = total_posts = 0
        hit429 = False
        last = f"{base}/{board}"
        for slug in threads[:COUNT]:
            d = random.uniform(*DELAY)  # noqa: S311
            await asyncio.sleep(d)
            r = await page.goto(f"{base}/{slug}", wait_until="domcontentloaded", timeout=90_000, referer=last)
            last = f"{base}/{slug}"
            if r is None:
                log(f"  {slug[:40]} no-response"); continue
            if r.status == 429:
                hit429 = True
                log(f"  429 at thread #{visited + 1} -> ABORT (silent, not hammering)")
                break
            h = await page.content()
            np = posts_in(h)
            total_posts += np
            visited += 1
            log(f"  #{visited:2d} [{r.status}] posts={np:2d} waited={d:4.0f}s  {title_of(h)[:46]}")

        log("")
        log(f"DONE: {visited} threads read, {total_posts} posts collected, "
            f"429s hit: {'YES — profile too hot' if hit429 else 'ZERO (ghost held)'}")
        await b.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: python -u lurk.py http://<onion>/ warmed.cookies.txt [Forum-Slug]")
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
