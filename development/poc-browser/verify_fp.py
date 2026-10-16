#!/usr/bin/env python3
# poc-browser: does our Playwright-Firefox reproduce the operator's stock Tor
# Browser fingerprint? Launches FF with the browse.py config, runs the same
# probes, and diffs against the real TB capture (TARGET). No Tor needed — these
# are local fingerprint fields. DIFFs are the residual config work.
from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

TB_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
PREFS = {
    "general.useragent.override": TB_UA,
    "privacy.resistFingerprinting": True,
    "media.peerconnection.enabled": False,
    "dom.webdriver.enabled": False,
    "app.update.enabled": False,
    "intl.accept_languages": "en-US, en",  # -> navigator.languages == ['en-US','en'] (match TB)
}
# navigator.webdriver stays true under Playwright even with the pref; redefine it
# before any page script runs. Standard stealth patch; enough for a MyBB pf-auto.
WEBDRIVER_PATCH = "Object.defineProperty(navigator, 'webdriver', {get: () => false});"

# Ground truth: the operator's stock Tor Browser, captured on the onion.
TARGET = {
    "userAgent": TB_UA,
    "platform": "Linux x86_64",
    "languages": "en-US,en",
    "hardwareConcurrency": 4,
    "webdriver": False,
    "buildID": "20181001000000",
    "timeZone": "Atlantic/Reykjavik",
    "webglUnmaskedRenderer": "Mozilla",
    "webglMaxTexture": 2048,
    "innerWidth": 1600,
    "innerHeight": 500,
    "devicePixelRatio": 2,
    "userAgentData": "undefined",
}

PROBE = r"""() => {
  const n = navigator, s = screen, out = {};
  out.userAgent = n.userAgent;
  out.platform = n.platform;
  out.languages = (n.languages||[]).join(',');
  out.hardwareConcurrency = n.hardwareConcurrency;
  out.webdriver = n.webdriver;
  out.buildID = n.buildID;
  out.userAgentData = n.userAgentData ? 'present' : 'undefined';
  out.timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  out.innerWidth = window.innerWidth; out.innerHeight = window.innerHeight;
  out.devicePixelRatio = window.devicePixelRatio;
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl');
    const d = gl.getExtension('WEBGL_debug_renderer_info');
    out.webglUnmaskedRenderer = d ? gl.getParameter(d.UNMASKED_RENDERER_WEBGL) : 'blocked';
    out.webglMaxTexture = gl.getParameter(gl.MAX_TEXTURE_SIZE);
  } catch (e) { out.webglUnmaskedRenderer = 'ERR'; }
  return out;
}"""


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True, firefox_user_prefs=PREFS)
        ctx = await browser.new_context(
            user_agent=TB_UA,
            viewport={"width": 1600, "height": 500},
            device_scale_factor=2,
            timezone_id="Atlantic/Reykjavik",
        )  # no locale= : let RFP + intl.accept_languages drive languages (match TB)
        await ctx.add_init_script(WEBDRIVER_PATCH)
        page = await ctx.new_page()
        await page.goto("about:blank")
        got = await page.evaluate(PROBE)
        await browser.close()

    print(f"{'field':24} {'TARGET (real TB)':28} {'OURS (playwright-ff)':28} ok")
    print("-" * 86)
    ok_all = True
    for k, want in TARGET.items():
        have = got.get(k)
        ok = str(have) == str(want)
        ok_all &= ok
        print(f"{k:24} {str(want):28.28} {str(have):28.28} {'OK' if ok else 'DIFF'}")
    print("-" * 86)
    print("MATCH" if ok_all else "DIFFs above = residual config work (version-specific RFP drift)")


if __name__ == "__main__":
    asyncio.run(main())
