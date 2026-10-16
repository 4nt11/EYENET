#!/usr/bin/env python3
# poc-browser: clearnet DDoS-Guard lurk test.
#
# Replays a warmed "Copy as cURL" session into Playwright-Firefox tuned to the
# MINT browser (plain Firefox, NOT Tor Browser: no RFP, no letterbox, no onion
# prefs) and goes DIRECT (no Tor). Single gentle lurk — the session is a
# logged-in account, so we land / classify / dwell / scroll and do NOT crawl.
# Persists storage_state so the rotated __ddg* cookies (DDoS-Guard reissues them
# per response) carry into the next run — the sticky jar ANTI flagged.
#
#   python browse_ddg.py https://raidforums.im/ raidforums-im.curl raidforums.state.json
from __future__ import annotations

import asyncio
import random
import re
import sys
import time

from playwright.async_api import async_playwright

import human

_T0 = time.monotonic()
_DEFAULT_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0"


def log(m: str) -> None:
    print(f"[{time.monotonic() - _T0:6.1f}s] {m}")


def _header(blob: str, name: str) -> str | None:
    m = re.search(rf"-H\s+(['\"])\s*{name}:\s*(.*?)\1", blob, re.S | re.I)
    return m.group(2).strip() if m else None


def cookies_from_curl(blob: str, origin: str) -> list[dict]:
    """Every cookie in the curl's Cookie header -> Playwright add_cookies dicts.
    url=origin lets Playwright set domain/path/secure from the https origin."""
    cs = _header(blob, "cookie") or ""
    out: list[dict] = []
    for part in cs.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, val = part.split("=", 1)
        if name.strip():
            out.append({"name": name.strip(), "value": val.strip(), "url": origin})
    return out


def classify(html: str, title: str) -> str:
    h = (html + " " + title).lower()
    # STRUCTURE FIRST. A ban/challenge is an INTERSTITIAL that REPLACES the forum,
    # so only trust those verdicts when the forum chrome is ABSENT. Otherwise a
    # thread whose CONTENT merely says "account is banned" false-reads as a ban
    # while we're still logged in (that bug manufactured a bogus rung-3 "ban").
    logged_in = "member.php?action=logout" in h or ">log out<" in h or "usercp" in h
    forumish = any(k in h for k in ("showthread", "forumdisplay", 'class="post', "mybb"))
    if not (logged_in or forumish):
        if "ddos-guard" in h or "checking your browser" in h:
            return "DDOS-GUARD-CHALLENGE"
        if re.search(r"just a moment|challenge-platform|cf-mitigated|turnstile", h):
            return "CF-CHALLENGE"
        if re.search(r"your account (has been|is) banned|you (have been|are) banned|not allowed to access", h):
            return "BANNED"
        if re.search(r"you must (be registered|login)|action=login", h):
            return "GUEST/LOGIN-WALL"
    if logged_in:
        return "LOGGED-IN"
    if forumish:
        return "FORUM-OK"
    return "UNKNOWN"


async def main(url: str, curl_path: str, out_state: str) -> None:
    origin = re.match(r"https?://[^/]+", url).group(0)
    blob = open(curl_path, encoding="utf-8").read()
    ua = _header(blob, "user-agent") or _DEFAULT_UA
    accept_lang = _header(blob, "accept-language") or "en-US,en;q=0.9"

    async with async_playwright() as p:
        # Plain-FF prefs ONLY (match the mint). No socks_remote_dns, no RFP.
        browser = await p.firefox.launch(
            headless=True,
            firefox_user_prefs={
                "general.useragent.override": ua,
                "dom.webdriver.enabled": False,
                "app.update.enabled": False,
                "intl.accept_languages": "en-US, en",
            },
        )
        ctx = await browser.new_context(
            user_agent=ua,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            extra_http_headers={"Accept-Language": accept_lang},
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>false});"
        )
        cks = cookies_from_curl(blob, origin)
        await ctx.add_cookies(cks)
        n_ddg = sum(1 for c in cks if c["name"].startswith("__ddg"))
        log(f"UA={ua}")
        log(f"loaded {len(cks)} cookies ({n_ddg} __ddg, direct clearnet) -> {origin}")

        page = await ctx.new_page()
        log(f"GET {url}")
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        title = await page.title()
        verdict = classify(await page.content(), title)
        log(f"HTTP {resp.status if resp else '?'}  title={title!r}  -> {verdict}")

        # A DDoS-Guard JS challenge may auto-solve; give it one settle window.
        if verdict in ("DDOS-GUARD-CHALLENGE", "CF-CHALLENGE"):
            await page.wait_for_timeout(7000)
            title = await page.title()
            verdict = classify(await page.content(), title)
            log(f"after 7s settle -> {verdict}  title={title!r}")

        if verdict in ("LOGGED-IN", "FORUM-OK"):
            log(f"CLEAN. dwell {await human.human_dwell('glance'):.1f}s")
            await human.human_scroll(page, random.randint(400, 1200))  # noqa: S311
        else:
            log("session did NOT land clean — stopping (no crawl)")

        await ctx.storage_state(path=out_state)
        held = cookies_from_curl(blob, origin)  # for the count line only
        log(f"saved storage_state -> {out_state} (replay-cookies in: {len(held)})")
        await browser.close()


if __name__ == "__main__":
    _url = sys.argv[1] if len(sys.argv) > 1 else "https://raidforums.im/"
    _curl = sys.argv[2] if len(sys.argv) > 2 else "raidforums-im.curl"
    _out = sys.argv[3] if len(sys.argv) > 3 else "raidforums.state.json"
    asyncio.run(main(_url, _curl, _out))
