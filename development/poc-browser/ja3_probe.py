#!/usr/bin/env python3
# JA3/JA4 PoC — settle whether curl-cffi's Firefox impersonation emits the same
# TLS fingerprint as a real Firefox (Playwright-FF), and how far bare httpx
# (OpenSSL) sits from both. This is the GATE for porting the collector off httpx.
#
# Hits a PUBLIC TLS reflector — fine for GENERIC client libs (httpx/curl-cffi/
# playwright are not sensitive). The real FF152-we-warm-accounts-with gets a
# SELF-HOSTED reflector later; never leak the warming browser's fp to a 3rd party.
#
#   python ja3_probe.py
from __future__ import annotations

import asyncio
import json

REFLECTOR = "https://tls.peet.ws/api/all"
FF_TARGET = "firefox147"  # closest curl-cffi target to our FF152 mint


def dig(d, key):
    """First value for `key` anywhere in a nested dict/list, else None."""
    if isinstance(d, dict):
        for k, v in d.items():
            if k == key:
                return v
            r = dig(v, key)
            if r is not None:
                return r
    elif isinstance(d, list):
        for v in d:
            r = dig(v, key)
            if r is not None:
                return r
    return None


def summ(tag: str, data: dict) -> tuple:
    ja3 = dig(data, "ja3_hash")
    ja4 = dig(data, "ja4")
    ak = dig(data, "akamai_fingerprint_hash")
    print(f"{tag:20} ja3={str(ja3)[:32]:32} ja4={str(ja4)[:44]:44} h2={str(ak)[:18]}")
    return (ja3, ja4)


async def via_httpx() -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=30) as c:
        return (await c.get(REFLECTOR)).json()


async def via_curlcffi() -> dict:
    from curl_cffi.requests import AsyncSession

    async with AsyncSession() as s:
        return (await s.get(REFLECTOR, impersonate=FF_TARGET)).json()


async def via_playwright() -> dict:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        b = await p.firefox.launch(headless=True)
        pg = await (await b.new_context()).new_page()
        await pg.goto(REFLECTOR, wait_until="domcontentloaded", timeout=60_000)
        txt = await pg.evaluate("() => document.body.innerText")
        await b.close()
        return json.loads(txt)


async def main() -> None:
    print(f"reflector={REFLECTOR}  curl-cffi target={FF_TARGET}\n")
    results: dict[str, tuple] = {}
    for tag, fn in (
        ("httpx/OpenSSL", via_httpx),
        (f"curl-cffi/{FF_TARGET}", via_curlcffi),
        ("playwright-FF", via_playwright),
    ):
        try:
            results[tag] = summ(tag, await fn())
        except Exception as e:  # noqa: BLE001 - PoC: report per-client failure, keep going
            print(f"{tag:20} ERROR {type(e).__name__}: {str(e)[:80]}")

    pw = results.get("playwright-FF")
    cc = next((v for k, v in results.items() if k.startswith("curl-cffi")), None)
    hx = results.get("httpx/OpenSSL")
    if cc and pw:
        print(f"\ncurl-cffi FF  JA4 == real FF JA4 ? {cc[1] == pw[1] and cc[1] is not None}")
        print(f"  curl-cffi : {cc[1]}")
        print(f"  real FF   : {pw[1]}")
    if hx and pw:
        print(f"httpx(OpenSSL) JA4 == real FF JA4 ? {hx[1] == pw[1] and hx[1] is not None}  (expect False — the Python tell)")
        print(f"  httpx     : {hx[1]}")


if __name__ == "__main__":
    asyncio.run(main())
