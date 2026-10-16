#!/usr/bin/env python3
# Self-hosted JA3/JA4 reflector + capture — nothing leaves the box.
#
# Reads the raw ClientHello off the socket (the TLS client speaks first, so no
# server cert / no completed handshake is needed), computes JA3/JA4 in pure
# stdlib, and captures three clients: curl-cffi firefox147, Playwright-FF, and the
# REAL system Firefox 152 (the browser that warms our accounts). It VALIDATES the
# parser against the tls.peet.ws ground-truth we already measured for curl-cffi +
# Playwright, and only trusts the FF152 number once the parser is proven correct.
#
#   python capture_ja3.py
from __future__ import annotations

import asyncio
import hashlib
import sys
import tempfile

# Ground-truth from tls.peet.ws (ja3_probe.py). If our parser reproduces these
# when curl-cffi/Playwright hit our reflector, the parser is correct.
KNOWN = {
    "curl-cffi/firefox147": ("6f7889b9fb1a62a9577e685c1fcfa919", "t13d1717h2_5b57614c22b0_3cbfd9057e0d"),
    "playwright-FF": ("424f6d9c8b8928c0a0489a4f1a0f3e89", "t13d1517h2_8daaf6152771_3cbfd9057e0d"),
}


def is_grease(v: int) -> bool:
    return (v >> 8) == (v & 0xFF) and (v & 0x0F) == 0x0A


def parse_client_hello(data: bytes) -> dict:
    if data[0] != 0x16:
        raise ValueError("not a TLS handshake record")
    rec_len = int.from_bytes(data[3:5], "big")
    hs = data[5 : 5 + rec_len]
    if hs[0] != 0x01:
        raise ValueError("not a ClientHello")
    p = 4
    legacy = int.from_bytes(hs[p : p + 2], "big")
    p += 2 + 32  # version + random
    p += 1 + hs[p]  # session id
    cl = int.from_bytes(hs[p : p + 2], "big")
    p += 2
    ciphers = [int.from_bytes(hs[p + i : p + i + 2], "big") for i in range(0, cl, 2)]
    p += cl
    p += 1 + hs[p]  # compression methods
    el = int.from_bytes(hs[p : p + 2], "big")
    p += 2
    end = p + el
    exts: list[int] = []
    curves: list[int] = []
    pf: list[int] = []
    sig: list[int] = []
    sni = False
    alpn: list[str] = []
    sv: list[int] = []
    while p < end:
        et = int.from_bytes(hs[p : p + 2], "big")
        ln = int.from_bytes(hs[p + 2 : p + 4], "big")
        d = hs[p + 4 : p + 4 + ln]
        p += 4 + ln
        exts.append(et)
        if et == 0x0A:  # supported_groups
            n = int.from_bytes(d[0:2], "big")
            curves = [int.from_bytes(d[2 + i : 4 + i], "big") for i in range(0, n, 2)]
        elif et == 0x0B:  # ec_point_formats
            pf = list(d[1 : 1 + d[0]])
        elif et == 0x0D:  # signature_algorithms
            n = int.from_bytes(d[0:2], "big")
            sig = [int.from_bytes(d[2 + i : 4 + i], "big") for i in range(0, n, 2)]
        elif et == 0x00:  # SNI
            sni = True
        elif et == 0x10:  # ALPN
            i = 2
            while i < len(d):
                pl = d[i]
                alpn.append(d[i + 1 : i + 1 + pl].decode("latin1"))
                i += 1 + pl
        elif et == 0x2B:  # supported_versions
            sv = [int.from_bytes(d[1 + i : 3 + i], "big") for i in range(0, d[0], 2)]
    return {"legacy": legacy, "ciphers": ciphers, "exts": exts, "curves": curves,
            "pf": pf, "sig": sig, "sni": sni, "alpn": alpn, "sv": sv}


def ja3(h: dict) -> str:
    cs = [c for c in h["ciphers"] if not is_grease(c)]
    ex = [e for e in h["exts"] if not is_grease(e)]
    cu = [c for c in h["curves"] if not is_grease(c)]
    s = (f'{h["legacy"]},{"-".join(map(str, cs))},{"-".join(map(str, ex))},'
         f'{"-".join(map(str, cu))},{"-".join(map(str, h["pf"]))}')
    return hashlib.md5(s.encode()).hexdigest()  # noqa: S324 - JA3 is defined as MD5


def ja4(h: dict) -> str:
    sv = [v for v in h["sv"] if not is_grease(v)]
    ver = max(sv) if sv else h["legacy"]
    vstr = {0x0304: "13", 0x0303: "12", 0x0302: "11", 0x0301: "10"}.get(ver, "00")
    cs = [c for c in h["ciphers"] if not is_grease(c)]
    ex = [e for e in h["exts"] if not is_grease(e)]
    alpn = f'{h["alpn"][0][0]}{h["alpn"][0][-1]}' if h["alpn"] else "00"
    a = f't{vstr}{"d" if h["sni"] else "i"}{min(len(cs), 99):02d}{min(len(ex), 99):02d}{alpn}'
    b = hashlib.sha256(",".join(f"{c:04x}" for c in sorted(cs)).encode()).hexdigest()[:12]
    exc = sorted(e for e in ex if e not in (0x00, 0x10))
    cstr = ",".join(f"{e:04x}" for e in exc) + "_" + ",".join(f"{s:04x}" for s in h["sig"])
    c = hashlib.sha256(cstr.encode()).hexdigest()[:12]
    return f"{a}_{b}_{c}"


_caps: list = []


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        data = await asyncio.wait_for(reader.read(5), 6)
        if len(data) >= 5:
            rl = int.from_bytes(data[3:5], "big")
            while len(data) < 5 + rl:
                c = await asyncio.wait_for(reader.read(5 + rl - len(data)), 6)
                if not c:
                    break
                data += c
            h = parse_client_hello(data)
            _caps.append({
                "ja3": ja3(h), "ja4": ja4(h),
                "nc": len([x for x in h["ciphers"] if not is_grease(x)]),
                "ne": len([x for x in h["exts"] if not is_grease(x)]),
                "exthex": " ".join(f"{e:04x}" for e in h["exts"] if not is_grease(e)),
            })
    except Exception as e:  # noqa: BLE001 - reflector: record parse failure, keep serving
        _caps.append({"err": f"{type(e).__name__}: {e}"})
    finally:
        writer.close()


async def grab(trigger=None, cmd=None, wait_s: float = 25.0) -> list:
    start = len(_caps)
    if cmd:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        for _ in range(int(wait_s * 10)):
            if len(_caps) > start:
                break
            await asyncio.sleep(0.1)
        await asyncio.sleep(3)  # linger: catch sibling/navigation connections, not just the first
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), 5)
        except (ProcessLookupError, asyncio.TimeoutError):
            pass
    else:
        try:
            await trigger
        except Exception:  # noqa: BLE001 - client errors on our no-cert handshake; expected
            pass
        for _ in range(50):
            if len(_caps) > start:
                break
            await asyncio.sleep(0.1)
    return _caps[start:]


def _distinct(caps: list) -> list:
    seen, out = set(), []
    for c in caps:
        key = c.get("ja4") or c.get("err")
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


async def main() -> None:
    # Connect via a HOSTNAME so clients send SNI. Pass a NON-loopback host (e.g.
    # <lan-ip-dashed>.nip.io) as argv[1] so Firefox treats it as a public host and
    # emits its full ClientHello (incl. compress_certificate 0x001b) — loopback
    # makes FF drop that. Bind all interfaces so the LAN IP is reachable.
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    server = None
    for cand in range(44443, 44473):
        try:
            server = await asyncio.start_server(handle, "0.0.0.0", cand)  # noqa: S104 - lab reflector
            port = cand
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError("no free port in 44443-44472")
    url = f"https://{host}:{port}/"
    print(f"reflector on {url}\n")
    results: dict[str, dict] = {}

    from curl_cffi.requests import AsyncSession

    async def cc() -> None:
        async with AsyncSession() as s:
            await s.get(url, impersonate="firefox147", timeout=8)

    results["curl-cffi/firefox147"] = await grab(trigger=cc())

    from playwright.async_api import async_playwright

    async def pw() -> None:
        async with async_playwright() as p:
            b = await p.firefox.launch(headless=True)
            pg = await (await b.new_context()).new_page()
            try:
                await pg.goto(url, timeout=8000)
            except Exception:  # noqa: BLE001
                pass
            await b.close()

    results["playwright-FF"] = await grab(trigger=pw())

    prof = tempfile.mkdtemp(prefix="ja3ff_")
    results["firefox-152(system)"] = await grab(
        cmd=["/usr/bin/firefox", "--headless", "--no-remote", "--profile", prof, url], wait_s=30
    )

    server.close()

    print(f"{'client':26} {'JA4':46} nc/ne")
    for k, caps in results.items():
        for i, v in enumerate(_distinct(caps)):
            tag = k if i == 0 else f"  {k}~alt{i}"
            if "err" in v:
                print(f"{tag:26} ERROR {v['err']}")
            else:
                print(f"{tag:26} {v['ja4']:46} {v['nc']}/{v['ne']}")
                print(f"{'':26} exts: {v['exthex']}")

    print("\n--- parser validation vs peet.ws ground-truth ---")
    ok = True
    for k, (j3, j4) in KNOWN.items():
        matches = [c for c in results.get(k, []) if c.get("ja3") == j3 and c.get("ja4") == j4]
        print(f"{k:22} {'OK (a capture matches peet.ws exactly)' if matches else 'NO MATCH'}")
        ok = ok and bool(matches)
    print(f"PARSER {'VALIDATED' if ok else 'unvalidated'}")

    ffd = [c for c in _distinct(results.get("firefox-152(system)", [])) if "ja4" in c]
    print(f"\n*** FF152 distinct ClientHellos captured: {len(ffd)} ***")
    for v in ffd:
        has001b = " 001b " in f" {v['exthex']} "
        print(f"    JA4={v['ja4']}  ciphers={v['nc']} exts={v['ne']}  has_compress_cert(001b)={has001b}")


if __name__ == "__main__":
    asyncio.run(main())
