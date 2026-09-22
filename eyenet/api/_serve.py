"""Hypercorn launcher for the EYENET operator API (API_PLAN §12.1).

HTTP/1.1 is forbidden. ALPN offers ``h2`` (and ``h3`` when
``EYENET_API_ENABLE_H3=1``), never ``h11`` — clients that speak only HTTP/1.1
get a handshake failure, by design (§12.1.1). uvicorn couldn't do this; it's
h11-only. Hence Hypercorn.

TLS termination is either in-process (``--certfile``/``--keyfile``) or at an
upstream proxy that speaks h2/h3 backwards. A non-loopback bind with neither is
refused: host stats and evidence bytes never cross a public interface in
cleartext. QUIC (h3) is TLS-only, so it requires an in-process cert.
"""

from __future__ import annotations

from hypercorn.config import Config

# Hosts where a cleartext bind is acceptable because nothing but this box (or an
# upstream proxy on the same box) can reach it.
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


def build_config(
    host: str,
    port: int,
    *,
    enable_h3: bool = False,
    certfile: str | None = None,
    keyfile: str | None = None,
    workers: int = 1,
    allow_insecure_bind: bool = False,
) -> Config:
    """Build a Hypercorn ``Config`` that offers h2 (+h3), never h1.

    Raises ``RuntimeError`` on an insecure configuration rather than quietly
    exposing plaintext: a public bind without TLS, or h3 without a cert.
    """
    tls = certfile is not None and keyfile is not None
    loopback = host in _LOOPBACK

    if not loopback and not tls and not allow_insecure_bind:
        raise RuntimeError(
            f"refusing to bind {host!r} without TLS: pass --certfile/--keyfile, "
            "or --allow-insecure-bind if TLS is terminated upstream"
        )
    if enable_h3 and not tls:
        raise RuntimeError("HTTP/3 (QUIC) is TLS-only: --certfile/--keyfile required")

    cfg = Config()
    cfg.bind = [f"{host}:{port}"]
    # The whole point: h2 first, h3 when asked, h11 NEVER in the list.
    cfg.alpn_protocols = ["h2", "h3"] if enable_h3 else ["h2"]
    cfg.workers = workers
    if tls:
        cfg.certfile = certfile
        cfg.keyfile = keyfile
    if enable_h3:
        cfg.quic_bind = [f"{host}:{port}"]
    return cfg


if __name__ == "__main__":
    # ponytail: self-check for the security guard — the one branch that, if
    # wrong, leaks plaintext on a public interface.
    assert build_config("127.0.0.1", 8000).alpn_protocols == ["h2"]
    assert build_config(
        "0.0.0.0", 443, enable_h3=True, certfile="c.pem", keyfile="k.pem"
    ).alpn_protocols == ["h2", "h3"]
    for bad in (
        lambda: build_config("0.0.0.0", 8000),  # public + no TLS
        lambda: build_config("127.0.0.1", 8000, enable_h3=True),  # h3 + no TLS
    ):
        try:
            bad()
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected RuntimeError on insecure config")
    # Upstream-TLS proxy escape hatch is honored.
    assert build_config("0.0.0.0", 8000, allow_insecure_bind=True).bind == ["0.0.0.0:8000"]
    print("ok")
