#!/usr/bin/env python3
# End-to-end: does curl-cffi actually ride raidforums' DDoS-Guard with the warmed
# jar? One GET, primary jar, direct clearnet, FF147 TLS impersonation + FF152 UA
# (matching the cookie mint + the proven Playwright config). Confirms LOGGED-IN,
# not a __ddg challenge. No soak, no crawl.
from __future__ import annotations

import asyncio
import re
import sys

from curl_cffi.requests import AsyncSession

from browse_ddg import _header, classify

CURL = "raidforums-im.curl"
TARGET = "firefox147"


def cookie_dict(blob: str) -> dict:
    cs = _header(blob, "cookie") or ""
    out = {}
    for p in cs.split(";"):
        p = p.strip()
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
    return out


async def main(url: str) -> None:
    blob = open(CURL, encoding="utf-8").read()
    ua = _header(blob, "user-agent")
    al = _header(blob, "accept-language") or "en-US,en;q=0.9"
    cookies = cookie_dict(blob)
    print(f"curl-cffi impersonate={TARGET}  UA={ua}")
    print(f"cookies: {list(cookies)} ({sum(1 for k in cookies if k.startswith('__ddg'))} __ddg)")
    print(f"GET {url}")
    async with AsyncSession() as s:
        r = await s.get(
            url,
            impersonate=TARGET,
            cookies=cookies,
            headers={"User-Agent": ua, "Accept-Language": al},
            timeout=40,
        )
    text = r.text
    m = re.search(r"<title>(.*?)</title>", text, re.I | re.S)
    title = m.group(1).strip() if m else ""
    low = text.lower()
    print(f"HTTP {r.status_code}  len={len(text)}  title={title[:70]!r}")
    print(f"VERDICT: {classify(text, title)}")
    print(f"  logged-in marker : {'member.php?action=logout' in low or 'usercp' in low}")
    print(f"  ddg challenge    : {'checking your browser' in low or 'ddos-guard' in low}")
    print(f"  thread links seen: {len(re.findall(r'Thread-', text))}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "https://raidforums.im/Forum-Databases"))
