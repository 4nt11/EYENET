#!/usr/bin/env python3
# poc-browser: measure a forum's CLIENT-SIDE anti-abuse surface before deciding
# whether a human-driving browser is even needed. Loads the target as a guest
# over Tor (Firefox) and reports every network beacon + telemetry/fingerprint
# script it sees. If this comes back empty, pf-auto is server-side and the real
# fix is pacing + a clean session, not a headless browser.
#
#   python recon.py http://<onion>/
from __future__ import annotations

import asyncio
import re
import sys

from playwright.async_api import async_playwright

TB_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
SOCKS = "socks5://127.0.0.1:9050"

# Firefox prefs to resolve .onion over Tor and present a Tor-Browser-ish client.
PREFS = {
    "network.proxy.socks_remote_dns": True,  # .onion resolves via Tor, not locally — REQUIRED
    "general.useragent.override": TB_UA,
    "privacy.resistFingerprinting": True,  # Tor Browser default
    "media.peerconnection.enabled": False,  # kill WebRTC IP leaks
    "dom.webdriver.enabled": False,  # hide navigator.webdriver
    "app.update.enabled": False,
    "intl.accept_languages": "en-US, en",  # -> navigator.languages ['en-US','en'] (match TB)
}
WEBDRIVER_PATCH = "Object.defineProperty(navigator, 'webdriver', {get: () => false});"

# Heuristics for client-side scoring JS.
_TELEMETRY = [
    (r"addEventListener\(\s*['\"](mousemove|mousedown|scroll|keydown|keyup|touchstart)['\"]", "input-event listener"),
    (r"navigator\.sendBeacon", "sendBeacon"),
    (r"(canvas|getImageData|toDataURL|measureText)", "canvas fingerprint"),
    (r"(webgl|getParameter|WEBGL_debug_renderer_info)", "webgl fingerprint"),
    (r"navigator\.(plugins|hardwareConcurrency|deviceMemory|languages)", "navigator enumeration"),
    (r"performance\.(now|timing|getEntries)", "timing beacon"),
    (r"(fingerprint|fpjs|botd|datadome|perimeterx|px-|hcaptcha|turnstile|challenge-platform)", "named anti-bot"),
]
_BEACON_URL = re.compile(r"/(track|beacon|stat|collect|telemetry|event|analytics|metric)s?\b", re.I)


async def main(url: str) -> None:
    reqs: list[tuple[str, str]] = []
    async with async_playwright() as p:
        browser = await p.firefox.launch(
            headless=True, proxy={"server": SOCKS}, firefox_user_prefs=PREFS
        )
        ctx = await browser.new_context(
            user_agent=TB_UA,
            viewport={"width": 1600, "height": 500},
            device_scale_factor=2,
            timezone_id="Atlantic/Reykjavik",
        )
        await ctx.add_init_script(WEBDRIVER_PATCH)
        page = await ctx.new_page()
        page.on("request", lambda r: reqs.append((r.method, r.url)))
        print(f"[recon] GET {url} over Tor ...")
        resp = await page.goto(url, wait_until="networkidle", timeout=120_000)
        await asyncio.sleep(3)  # let any deferred beacons fire
        html = await page.content()
        status = resp.status if resp else "?"
        print(f"[recon] HTTP {status}  bytes={len(html)}")

        banned = bool(re.search(r"account is banned|ban appeal|pf-auto", html, re.I))
        print(f"[recon] banned/guest-gated page: {banned}")

        # Third-party / beacon-looking requests (first-party onion asset loads are fine).
        host = re.sub(r"^https?://", "", url).split("/")[0]
        beacons = [(m, u) for (m, u) in reqs if _BEACON_URL.search(u) or (host not in u and u.startswith("http"))]
        print(f"\n[recon] network requests: {len(reqs)} total, {len(beacons)} beacon/off-host:")
        for m, u in beacons[:15]:
            print(f"    {m} {u[:100]}")

        print("\n[recon] client-side scoring signals in page scripts:")
        hits = [(label, len(re.findall(pat, html, re.I))) for pat, label in _TELEMETRY]
        hits = [(l, n) for (l, n) in hits if n]
        for label, n in hits:
            print(f"    [{n:3d}] {label}")
        if not hits:
            print("    (none) — no obvious client-side telemetry/fingerprinting")

        print("\n[recon] VERDICT:",
              "client-side scoring LIKELY -> need a real browser + human input"
              if (hits or beacons) else
              "no client-side scoring seen -> pf-auto is server-side; pacing + clean session is the lever")
        await browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python recon.py http://<onion>/")
    asyncio.run(main(sys.argv[1]))
