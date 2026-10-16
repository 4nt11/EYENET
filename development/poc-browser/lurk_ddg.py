#!/usr/bin/env python3
# poc-browser: clearnet DDoS-Guard SOAK probe.
#
# Lurk-crawls a category at a chosen cadence inside ONE browser context (so
# DDoS-Guard's rotated __ddg* stays live), paginating to keep finding fresh
# threads, and runs UNTIL: the account is banned, a challenge appears, or the
# time budget elapses. Per thread it logs a tiny preview (author / date / title).
#
# modes:  human = full read dwell + big scroll
#         light = short scroll + token pause
#         raw   = near-zero: no scroll, no dwell, just paced GETs
#
#   python lurk_ddg.py <cat_url> <curl> <lo> <hi> <budget> <logfile> <mode>
from __future__ import annotations

import asyncio
import random
import re
import sys
import time

from playwright.async_api import Error as PwError, async_playwright

import human
from browse_ddg import _DEFAULT_UA, _header, classify, cookies_from_curl

_T0 = time.monotonic()
_LOG = None  # set in main

_PREVIEW_JS = r"""() => {
  const post = document.querySelector('div.post[id^="post_"]') || document;
  const a = post.querySelector('.post_user-profile a, .post__user-profile a, .author_information a, strong.largetext a, a[href*="User-"]');
  const author = a ? a.textContent.trim() : '';
  const d = post.querySelector('span.post_date, .post__date, .post_date');
  const date = d ? d.textContent.trim().split('\n')[0].trim() : '';
  return {author, date};
}"""


def log(m: str) -> None:
    line = f"[{time.monotonic() - _T0:7.1f}s] {m}"
    print(line, flush=True)
    if _LOG is not None:
        _LOG.write(line + "\n")
        _LOG.flush()


async def wait_cadence(lo: float, hi: float) -> None:
    await asyncio.sleep(random.uniform(lo, hi))  # noqa: S311 - pacing jitter, not crypto


async def preview(page) -> tuple[str, str, str]:
    """Best-effort OP author / date / title for the tail preview (never fatal)."""
    title = (await page.title()).replace(" - RaidForums", "").strip()
    try:
        pv = await page.evaluate(_PREVIEW_JS)
    except Exception:  # noqa: BLE001 - preview is a nicety; default and move on
        pv = {}
    return pv.get("author", ""), pv.get("date", ""), title


async def safe_goto(page, url: str):
    """page.goto that tolerates a transient navigation error (e.g.
    NS_ERROR_NET_ERROR_RESPONSE on a MyBB action=lastpost redirect — the page is
    fine in a real browser). Returns the response, or None so the caller skips
    the one bad request instead of the whole soak dying on it."""
    try:
        return await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except PwError as e:
        log(f"    nav-error (skipped): {str(e).splitlines()[0][:90]}")
        return None


def _cat_page(cat_url: str, n: int) -> str:
    return cat_url if n <= 1 else f"{cat_url}?page={n}"


async def main(
    cat_url: str, curl_path: str, lo: float, hi: float, budget: float, logpath: str, mode: str
) -> None:
    global _LOG
    _LOG = open(logpath, "a", buffering=1, encoding="utf-8")  # noqa: SIM115 - long-lived sink
    origin = re.match(r"https?://[^/]+", cat_url).group(0)
    blob = open(curl_path, encoding="utf-8").read()
    ua = _header(blob, "user-agent") or _DEFAULT_UA
    al = _header(blob, "accept-language") or "en-US,en;q=0.9"
    log(f"=== SOAK START cat={cat_url} jar={curl_path} cadence={lo}-{hi}s budget={budget:.0f}s mode={mode} ===")

    stop = None
    reqs = threads = nav_errors = 0
    async with async_playwright() as p:
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
            extra_http_headers={"Accept-Language": al},
        )
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>false});")
        await ctx.add_cookies(cookies_from_curl(blob, origin))
        page = await ctx.new_page()

        visited: set[str] = set()
        cat_n = 1
        while time.monotonic() - _T0 < budget and stop is None:
            r = await safe_goto(page, _cat_page(cat_url, cat_n))
            reqs += 1
            if r is None:
                stop = f"category p{cat_n} nav-error"
                break
            v = classify(await page.content(), await page.title())
            log(f"category p{cat_n}: HTTP {r.status if r else '?'} -> {v}")
            if v in ("DDOS-GUARD-CHALLENGE", "CF-CHALLENGE"):
                stop = f"CHALLENGE ({v}) on category p{cat_n}"
                break
            if v == "BANNED":
                stop = f"BANNED on category p{cat_n}"
                break
            if v not in ("LOGGED-IN", "FORUM-OK"):
                stop = f"category p{cat_n} not clean ({v})"
                break
            if mode != "raw":
                await human.human_scroll(page, random.randint(150, 450) if mode == "light" else random.randint(500, 1400))  # noqa: S311

            hrefs = await page.eval_on_selector_all(
                "a[href*='Thread-']", "els => els.map(e => e.getAttribute('href'))"
            )
            fresh = []
            for h in hrefs:
                if h and "Thread-" in h:
                    u = h if h.startswith("http") else origin + "/" + h.lstrip("/")
                    if u not in visited:
                        fresh.append(u)
            fresh = list(dict.fromkeys(fresh))
            log(f"  {len(fresh)} fresh threads on p{cat_n}")
            if not fresh:
                stop = f"no fresh threads past p{cat_n} (end of category)"
                break

            for url in fresh:
                if time.monotonic() - _T0 >= budget:
                    break
                await wait_cadence(lo, hi)
                r = await safe_goto(page, url)
                reqs += 1
                visited.add(url)
                if r is None:
                    nav_errors += 1
                    if nav_errors >= 8:
                        stop = f"{nav_errors} consecutive nav-errors — possible soft-block after {threads} threads"
                        break
                    continue
                nav_errors = 0
                v = classify(await page.content(), await page.title())
                if v in ("DDOS-GUARD-CHALLENGE", "CF-CHALLENGE"):
                    stop = f"CHALLENGE ({v}) after {reqs} reqs / {threads} threads"
                    log(f"[t{threads + 1}] {v} HTTP {r.status if r else '?'}")
                    break
                if v == "BANNED":
                    stop = f"BANNED after {reqs} reqs / {threads} threads"
                    log(f"[t{threads + 1}] {v} HTTP {r.status if r else '?'}")
                    break
                threads += 1
                author, date, title = await preview(page)
                log(f"[t{threads}] {v} {r.status if r else '?'} | {author or '?'} | {date or '?'} | {title}")
                if mode == "human":
                    await human.human_scroll(page, random.randint(700, 2000))  # noqa: S311
                    await human.human_dwell("read")
                elif mode == "light":
                    await human.human_scroll(page, random.randint(150, 500))  # noqa: S311
                    await asyncio.sleep(random.uniform(0.3, 0.9))  # noqa: S311
            if stop is None:
                await wait_cadence(lo, hi)
                cat_n += 1

        await ctx.storage_state(path=logpath.replace(".log", ".state.json"))
        await browser.close()

    elapsed = time.monotonic() - _T0
    if stop is None:
        stop = f"TIME BUDGET reached ({budget:.0f}s) with no block"
    log(f"=== SOAK END: {stop} | {reqs} requests, {threads} threads, {elapsed:.0f}s ===")
    clean = "TIME BUDGET" in stop or "end of category" in stop
    log(f"=== READ: {'held CLEAN — no behavioural wall at this cadence' if clean else 'PUSHBACK — found an edge'} ===")
    if _LOG:
        _LOG.close()


if __name__ == "__main__":
    _cat = sys.argv[1] if len(sys.argv) > 1 else "https://raidforums.im/Forum-Databases"
    _curl = sys.argv[2] if len(sys.argv) > 2 else "raidforums-im.curl"
    _lo = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0
    _hi = float(sys.argv[4]) if len(sys.argv) > 4 else 12.0
    _budget = float(sys.argv[5]) if len(sys.argv) > 5 else 600.0
    _logp = sys.argv[6] if len(sys.argv) > 6 else "lurk_ddg.run.log"
    _mode = sys.argv[7] if len(sys.argv) > 7 else "human"
    asyncio.run(main(_cat, _curl, _lo, _hi, _budget, _logp, _mode))
