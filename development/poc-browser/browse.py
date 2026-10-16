#!/usr/bin/env python3
# poc-browser: a HUMAN browse session over Tor (Firefox), using human.py.
#
# Not a crawler. It behaves like a lurker: land on the index, read, bezier-move
# to a board, click, read a thread, scroll, maybe one more — with human dwell
# throughout. Logs a timeline and flags ban/challenge pages. Point it at a
# warmed session via a saved storageState (export one with Tor Browser login,
# or Playwright's context.storage_state()).
#
#   python browse.py http://<onion>/ [storage_state.json]
from __future__ import annotations

import asyncio
import random
import re
import sys
import time

from playwright.async_api import async_playwright

import human

TB_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
SOCKS = "socks5://127.0.0.1:9050"
PREFS = {
    "network.proxy.socks_remote_dns": True,  # .onion via Tor — REQUIRED
    "general.useragent.override": TB_UA,
    "privacy.resistFingerprinting": True,
    "media.peerconnection.enabled": False,
    "dom.webdriver.enabled": False,
    "app.update.enabled": False,
    "intl.accept_languages": "en-US, en",  # -> navigator.languages ['en-US','en'] (match TB)
}
# navigator.webdriver stays true under Playwright even with the pref; redefine it
# before page scripts run. Verified fingerprint-identical to stock TB (verify_fp.py).
WEBDRIVER_PATCH = "Object.defineProperty(navigator, 'webdriver', {get: () => false});"
_T0 = time.monotonic()


def log(msg: str) -> None:
    print(f"[{time.monotonic() - _T0:6.1f}s] {msg}")


def load_netscape(path: str) -> list[dict]:
    """Parse a Netscape cookies.txt into Playwright add_cookies dicts."""
    out: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            ln = raw.rstrip("\n")
            http_only = False
            if ln.startswith("#HttpOnly_"):
                ln, http_only = ln[len("#HttpOnly_"):], True
            elif ln.startswith("#") or not ln.strip():
                continue
            parts = ln.split("\t")
            if len(parts) != 7:
                continue
            domain, _flag, cpath, secure, expiry, name, value = parts
            out.append({
                "name": name, "value": value,
                "domain": domain.lstrip("."), "path": cpath or "/",
                "expires": int(expiry) if expiry.isdigit() else -1,
                "httpOnly": http_only, "secure": secure.upper() == "TRUE", "sameSite": "Lax",
            })
    return out


def classify(html: str) -> str:
    h = html.lower()
    if re.search(r"account is banned|ban appeal|pf-auto", h):
        return "BANNED"
    if re.search(r"just a moment|challenge-platform|turnstile|cf-mitigated", h):
        return "CHALLENGE"
    if re.search(r"log in|must be registered|you must login", h) and "logout" not in h:
        return "GUEST/LOGIN-WALL"
    if "mybb" in h or "showthread" in h or "forumdisplay" in h:
        return "FORUM-OK"
    return "UNKNOWN"


async def click_a_board(page) -> bool:
    """Bezier-move to a random visible board link and click it like a human."""
    links = page.locator("a[href*='Forum-'], a[href*='/forums/'], a[href*='/foros/']")
    n = await links.count()
    if n == 0:
        log("no board links visible")
        return False
    el = links.nth(random.randint(0, min(n, 12) - 1))  # noqa: S311 - pick among the top few
    box = await el.bounding_box()
    if not box:
        return False
    target = (box["x"] + box["width"] * random.uniform(0.3, 0.7),  # noqa: S311 - land somewhere on the link
              box["y"] + box["height"] * random.uniform(0.3, 0.7))  # noqa: S311
    log(f"bezier-click board link at ({target[0]:.0f},{target[1]:.0f})")
    await human.human_click(page, target)
    return True


async def main(url: str, storage: str | None) -> None:
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True, proxy={"server": SOCKS}, firefox_user_prefs=PREFS)
        is_json = bool(storage and storage.endswith(".json"))
        ctx = await browser.new_context(
            user_agent=TB_UA,
            storage_state=storage if is_json else None,
            # Match the operator's real stock-TB fingerprint (captured on the onion):
            # UTC clock, en-US, letterboxed 1600x500 @ dpr 2. Keep these equal to the
            # browser that warms the account, or the fingerprint jumps mid-session.
            viewport={"width": 1600, "height": 500},
            device_scale_factor=2,
            timezone_id="Atlantic/Reykjavik",
        )  # no locale= : RFP + intl.accept_languages drive languages to match TB
        await ctx.add_init_script(WEBDRIVER_PATCH)
        if storage and not is_json:  # Netscape cookies.txt -> inject the warmed session
            cks = load_netscape(storage)
            await ctx.add_cookies(cks)
            log(f"loaded {len(cks)} cookies from {storage}")
        page = await ctx.new_page()

        log(f"GET {url}")
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        html = await page.content()
        log(f"HTTP {resp.status if resp else '?'}  -> {classify(html)}")
        if classify(html) in ("BANNED", "CHALLENGE"):
            log("stopping: session is not clean")
            await browser.close()
            return

        log(f"dwell (read index) {await human.human_dwell('glance'):.1f}s")
        await human.human_scroll(page, random.randint(400, 1200))  # noqa: S311

        if await click_a_board(page):
            await page.wait_for_load_state("domcontentloaded")
            html = await page.content()
            log(f"board -> {classify(html)}")
            log(f"dwell (read board) {await human.human_dwell('read'):.1f}s")
            await human.human_scroll(page, random.randint(600, 1800))  # noqa: S311
            # read one thread
            threads = page.locator("a[href*='Thread-'], a[href*='/threads/'], a[href*='/post/']")
            if await threads.count():
                box = await threads.first.bounding_box()
                if box:
                    log("bezier-click into a thread")
                    await human.human_click(page, (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2))
                    await page.wait_for_load_state("domcontentloaded")
                    log(f"thread -> {classify(await page.content())}")
                    log(f"dwell (read thread) {await human.human_dwell('read'):.1f}s")
                    await human.human_scroll(page, random.randint(800, 2500))  # noqa: S311

        log("session done (clean). Save cookies with context.storage_state(path=...) if you want to reuse.")
        await browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python browse.py http://<onion>/ [storage_state.json]")
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
