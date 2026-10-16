# SPDX-License-Identifier: AGPL-3.0-or-later
"""Checksum validation for crypto-address indicator kinds — the CODED gate.

The RE2 ruleset (:mod:`eyenet.linker.indicator_rules`) can only *shape*-match an
address. That is not enough: base58's alphabet is a near-superset of lowercase
hex (it only drops ``0``), so any 32-char hex hash (MD5, a hyphen-stripped UUID,
a ``vector_signature``) that starts with ``1``/``3`` and happens to contain no
``0`` slips straight through the BTC-legacy pattern and gets stored as a wallet.
At operator scale that is a steady drip of false indicators poisoning linkage.

Real addresses carry their own checksum, which a regex cannot express. This
module is that check — the same "ruleset finds candidates, coded layer validates"
split EYENET already uses for domains (tldextract) and IPs (ipaddress). Call
:func:`validate_address` with the *surface* form (never the case-folded norm:
base58 and EIP-55 are both case-significant).

Per family:
  * ``wallet_btc``  — base58check (P2PKH ver 0x00 / P2SH ver 0x05), or bech32 /
    bech32m for ``bc1`` segwit.
  * ``wallet_tron`` — base58check, version byte 0x41.
  * ``wallet_eth``  — structural ``0x`` + 40 hex; EIP-55 keccak-256 mixed-case
    checksum verified when the address is actually mixed-case (all-one-case has
    no checksum by spec and is accepted).
  * ``wallet_xmr``  — Monero block-base58 decode + keccak-256 checksum.
  * anything else   — not a crypto kind; returns True (no gate).

keccak-256 is NOT ``hashlib.sha3_256`` (NIST SHA-3 uses different padding); it
comes from pycryptodome (a declared dependency), which ships Ethereum's original
Keccak.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from Crypto.Hash import (
    keccak,  # nosec B413 — pycryptodome (maintained), not legacy pyCrypto; it reuses the Crypto namespace
)

# Bitcoin/Monero/TRON share this base58 alphabet (no 0 O I l).
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58)}

# Protocol-fixed sizes (named so the checks read as spec, not magic numbers).
_B58CHECK_LEN = 25  # 1 version + 20 payload + 4 checksum (BTC legacy / TRON)
_BECH32_MAX_LEN = 90  # BIP-173 maximum encoded length
_ETH_HEX_LEN = 40  # a 20-byte EVM address as hex nibbles
_EIP55_NIBBLE_HI = 8  # keccak nibble >= 8 => that address char is upper-cased
_XMR_DECODED_LEN = 69  # 1 network byte + 32 spend + 32 view + 4 checksum


def _keccak256(data: bytes) -> bytes:
    h = keccak.new(digest_bits=256)
    h.update(data)
    return h.digest()


def _sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


# --- base58check (BTC legacy, TRON) -----------------------------------------


def _b58_decode(s: str) -> bytes | None:
    """Standard base58 decode with leading-zero (leading '1') restoration."""
    n = 0
    for c in s:
        v = _B58_INDEX.get(c)
        if v is None:
            return None
        n = n * 58 + v
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\x00" * (len(s) - len(s.lstrip("1"))) + body


def _b58check(s: str, versions: frozenset[int]) -> bool:
    raw = _b58_decode(s)
    if raw is None or len(raw) != _B58CHECK_LEN or raw[0] not in versions:
        return False
    return _sha256d(raw[:-4])[:4] == raw[-4:]


# --- bech32 / bech32m (BTC segwit bc1) --------------------------------------
# Reference algorithm from BIP-173 (bech32) and BIP-350 (bech32m).

_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_CONST = 1
_BECH32M_CONST = 0x2BC830A3


def _bech32_polymod(values: list[int]) -> int:
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            chk ^= gen[i] if (top >> i) & 1 else 0
    return chk


def _bech32_valid(addr: str) -> bool:
    # bech32 forbids mixed case; the bc1 rule folds to lower, and lowercasing a
    # valid address preserves its checksum, so normalise defensively.
    addr = addr.lower()
    pos = addr.rfind("1")
    if pos < 1 or pos + 7 > len(addr) or len(addr) > _BECH32_MAX_LEN:
        return False
    hrp, data_part = addr[:pos], addr[pos + 1 :]
    data: list[int] = []
    for c in data_part:
        d = _BECH32_CHARSET.find(c)
        if d == -1:
            return False
        data.append(d)
    expand = [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]
    const = _bech32_polymod(expand + data)
    # Witness v0 uses bech32; v1+ (taproot) uses bech32m. data[0] is the version.
    want = _BECH32_CONST if data[0] == 0 else _BECH32M_CONST
    return const == want


# --- Ethereum EIP-55 ---------------------------------------------------------

_HEX = frozenset("0123456789abcdefABCDEF")


def _eth_valid(addr: str) -> bool:
    if addr[:2] not in ("0x", "0X"):
        return False
    body = addr[2:]
    if len(body) != _ETH_HEX_LEN or any(c not in _HEX for c in body):
        return False
    # All-one-case carries no EIP-55 checksum and is valid by spec.
    if body == body.lower() or body == body.upper():
        return True
    # Mixed case: each hex letter's case encodes a bit of keccak256(lowercased).
    # keccak hex is 64 nibbles; EIP-55 uses the first 40 (one per address char).
    kh = _keccak256(body.lower().encode("ascii")).hex()
    # strict=False: kh is 64 nibbles, EIP-55 uses only the first 40 (one per char).
    for ch, kc in zip(body, kh, strict=False):
        if ch.isalpha() and ch != (ch.upper() if int(kc, 16) >= _EIP55_NIBBLE_HI else ch.lower()):
            return False
    return True


# --- Monero block-base58 -----------------------------------------------------
# Monero uses a block-wise base58 (not base58check): 8-byte blocks -> 11 chars,
# a trailing partial block, and a 4-byte keccak-256 (not double-sha256) checksum.

_XMR_ENC_SIZES = (0, 2, 3, 5, 6, 7, 9, 10, 11)  # encoded chars per N decoded bytes


def _xmr_decode_block(block: str, size: int) -> bytes | None:
    n = 0
    for c in block:
        v = _B58_INDEX.get(c)
        if v is None:
            return None
        n = n * 58 + v
    if n > (1 << (8 * size)) - 1:  # overlong encoding for this block size
        return None
    return n.to_bytes(size, "big")


def _xmr_b58_decode(s: str) -> bytes | None:
    full, rem = divmod(len(s), 11)
    out = bytearray()
    for i in range(full):
        b = _xmr_decode_block(s[i * 11 : i * 11 + 11], 8)
        if b is None:
            return None
        out += b
    if rem:
        if rem not in _XMR_ENC_SIZES:
            return None
        b = _xmr_decode_block(s[full * 11 :], _XMR_ENC_SIZES.index(rem))
        if b is None:
            return None
        out += b
    return bytes(out)


def _xmr_valid(addr: str) -> bool:
    raw = _xmr_b58_decode(addr)
    if raw is None or len(raw) != _XMR_DECODED_LEN:
        return False
    # Mainnet standard address = 18, mainnet subaddress = 42 (the [48] prefixes).
    if raw[0] not in (18, 42):
        return False
    return _keccak256(raw[:-4])[:4] == raw[-4:]


# --- dispatch ----------------------------------------------------------------

_BTC_VERSIONS = frozenset({0x00, 0x05})
_TRON_VERSIONS = frozenset({0x41})


def _btc_valid(value: str) -> bool:
    if value[:3].lower() == "bc1":
        return _bech32_valid(value)
    return _b58check(value, _BTC_VERSIONS)


_CHECKERS: dict[str, Callable[[str], bool]] = {
    "wallet_btc": _btc_valid,
    "wallet_tron": lambda v: _b58check(v, _TRON_VERSIONS),
    "wallet_eth": _eth_valid,
    "wallet_xmr": _xmr_valid,
}


def validate_address(kind: str, value: str) -> bool:
    """True if ``value`` is a checksum-valid address for ``kind``.

    Non-crypto kinds always pass (no gate). ``value`` must be the surface form,
    not the case-folded norm — base58 and EIP-55 are case-significant.
    """
    if not value:
        return False
    checker = _CHECKERS.get(kind)
    return checker(value) if checker is not None else True


__all__ = ["validate_address"]
