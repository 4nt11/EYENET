#!/usr/bin/env python3
"""POC: clear the DNSProxy gate, then pull a XenForo category as a guest.

Confirms whether leak categories are lurker-readable (thread rows render to a
guest jar) vs. session-gated. Reuses the 2-GET clearance, then feeds the real
category HTML straight into the shipping parser.

Usage:
    python pull_category.py https://xforums.st/forums/index-database.36/
    HTTPS_PROXY=socks5h://127.0.0.1:9050 python pull_category.py <url>   # over Tor

ponytail: 3-line clearance inlined (not worth importing) — this is throwaway.
"""

from __future__ import annotations

import sys
from urllib.parse import urlparse, urlencode

import httpx

from eyenet.collectors.forum import _xenforo as xf

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0"


def main(target: str) -> int:
    p = urlparse(target)
    origin = f"{p.scheme}://{p.netloc}"
    ret = p.path + (f"?{p.query}" if p.query else "")

    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=30) as c:
        # Clearance (same flow the module will own).
        token = c.get(f"{origin}/generate-challenge-token?{urlencode({'return': ret})}").text.strip()
        c.get(f"{origin}/verify-challenge?{urlencode({'token': token, 'return': ret})}")
        html = c.get(target).text

    print(f"category: {target}")
    print(f"bytes: {len(html)}  is_logged_in: {xf.is_logged_in(html)}")

    threads = xf.parse_thread_links(html)
    pages = xf.thread_page_count(html)
    print(f"thread_page_count (listing): {pages}")
    print(f"parse_thread_links: {len(threads)}")
    for u in threads[:25]:
        print(f"  {u}")
    if len(threads) > 25:
        print(f"  … +{len(threads) - 25} more")

    if threads:
        print("\n>>> LURKER-READABLE: guest jar sees thread rows. E1 crawl viable.")
        return 0
    print("\n>>> NO ROWS: category likely session-gated (needs a logged-in jar).")
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
