# SPDX-License-Identifier: AGPL-3.0-or-later
"""M9.B1 Ed25519 verification primitives (API_PLAN §5.7)."""

from __future__ import annotations

import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from eyenet.crypto import (
    build_canonical,
    build_signing_key_challenge_canonical,
    fingerprint,
    load_ed25519_public_key,
    verify_signature,
)

_FIELDS = ("GET", "/v1/files/abc?x=1", "req-123", "2026-06-09T12:00:00Z", "", "f" * 64)


def _raw_pub(priv: Ed25519PrivateKey) -> bytes:
    return priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


@pytest.mark.unit
def test_fingerprint_matches_known_der_vector() -> None:
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()

    der = pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    expected = hashlib.sha256(der).digest()[:8].hex()

    fp = fingerprint(pub)
    assert fp == expected
    assert len(fp) == 16


@pytest.mark.unit
def test_fingerprint_is_reproducible_from_raw_bytes() -> None:
    priv = Ed25519PrivateKey.generate()
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    fp1 = fingerprint(priv.public_key())
    fp2 = fingerprint(Ed25519PublicKey.from_public_bytes(raw))
    assert fp1 == fp2


@pytest.mark.unit
def test_verify_accepts_valid_signature() -> None:
    priv = Ed25519PrivateKey.generate()
    canonical = build_canonical(*_FIELDS)
    sig = priv.sign(canonical)
    assert verify_signature(priv.public_key(), canonical, sig) is True


@pytest.mark.unit
def test_verify_rejects_tampered_signature() -> None:
    priv = Ed25519PrivateKey.generate()
    canonical = build_canonical(*_FIELDS)
    sig = bytearray(priv.sign(canonical))
    sig[0] ^= 0x01  # flip a bit
    assert verify_signature(priv.public_key(), canonical, bytes(sig)) is False


@pytest.mark.unit
def test_verify_rejects_tampered_field() -> None:
    priv = Ed25519PrivateKey.generate()
    sig = priv.sign(build_canonical(*_FIELDS))
    tampered = build_canonical("POST", *_FIELDS[1:])  # method changed
    assert verify_signature(priv.public_key(), tampered, sig) is False


@pytest.mark.unit
def test_verify_rejects_wrong_key() -> None:
    priv = Ed25519PrivateKey.generate()
    other = Ed25519PrivateKey.generate()
    canonical = build_canonical(*_FIELDS)
    sig = priv.sign(canonical)
    assert verify_signature(other.public_key(), canonical, sig) is False


@pytest.mark.unit
def test_verify_rejects_malformed_signature_length() -> None:
    priv = Ed25519PrivateKey.generate()
    canonical = build_canonical(*_FIELDS)
    # Wrong-length signature raises InvalidSignature internally → False.
    assert verify_signature(priv.public_key(), canonical, b"too-short") is False


@pytest.mark.unit
def test_canonical_form_is_injection_proof() -> None:
    # Two distinct field-tuples where a naive separator-join would collide:
    # the boundary between url and request_id is shifted.
    a = build_canonical("GET", "/a", "b", "t", "h", "c")
    b = build_canonical("GET", "/a\x00b", "", "t", "h", "c")
    assert a != b

    # Classic '|'-join ambiguity: a URL containing the delimiter must not
    # be confusable with the next field starting.
    c = build_canonical("GET", "/x|y", "z", "t", "h", "c")
    d = build_canonical("GET", "/x", "y|z", "t", "h", "c")
    assert c != d


@pytest.mark.unit
def test_canonical_form_is_stable() -> None:
    assert build_canonical(*_FIELDS) == build_canonical(*_FIELDS)
    # The scheme tag is now ITSELF length-prefixed (4-byte BE length of the
    # tag = 13), so the canonical bytes lead with the framed scheme, not the
    # bare tag. The tag bytes themselves are preserved right after the length.
    scheme = b"EYENET-SIG-v1"
    assert build_canonical(*_FIELDS).startswith(len(scheme).to_bytes(4, "big") + scheme)


@pytest.mark.unit
def test_verify_returns_false_on_non_bytes_inputs() -> None:
    # An ABSENT signature/canonical header (None) — and any non-bytes shape —
    # is treated as INVALID, never raised. The B3 verify caller must not crash.
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    canonical = build_canonical(*_FIELDS)
    sig = priv.sign(canonical)

    assert verify_signature(pub, canonical, None) is False
    assert verify_signature(pub, None, sig) is False
    assert verify_signature(pub, canonical, 12345) is False  # type: ignore[arg-type]
    assert verify_signature(pub, ["not", "bytes"], sig) is False  # type: ignore[arg-type]
    # Sanity: bytearray/memoryview (bytes-like) still verify a valid sig.
    assert verify_signature(pub, canonical, bytearray(sig)) is True


# --- PHASE-4 signing-key registration proof-of-possession ----------------


@pytest.mark.unit
def test_challenge_canonical_binds_nonce_and_pubkey() -> None:
    priv = Ed25519PrivateKey.generate()
    pub_raw = _raw_pub(priv)
    base = build_signing_key_challenge_canonical("nonce-1", pub_raw)
    # Distinct nonce → distinct bytes.
    assert base != build_signing_key_challenge_canonical("nonce-2", pub_raw)
    # Distinct pubkey → distinct bytes.
    other_raw = _raw_pub(Ed25519PrivateKey.generate())
    assert base != build_signing_key_challenge_canonical("nonce-1", other_raw)
    # Stable.
    assert base == build_signing_key_challenge_canonical("nonce-1", pub_raw)


@pytest.mark.unit
def test_challenge_tag_distinct_from_other_schemes() -> None:
    """EYENET-SIGNING-KEY-CHALLENGE-v1 must not collide with EYENET-SIG-v1
    or EYENET-FAJ-v1 — a registration proof can never be replayed as a
    file-access request signature, nor as a journal-row preimage."""
    tag = b"EYENET-SIGNING-KEY-CHALLENGE-v1"
    framed = len(tag).to_bytes(4, "big") + tag
    canonical = build_signing_key_challenge_canonical("n", b"\x01" * 32)
    assert canonical.startswith(framed)
    # The per-request signing canonical leads with a DIFFERENT framed tag.
    assert not canonical.startswith(len(b"EYENET-SIG-v1").to_bytes(4, "big") + b"EYENET-SIG-v1")


@pytest.mark.unit
def test_pop_verify_accepts_valid_signature_over_challenge() -> None:
    priv = Ed25519PrivateKey.generate()
    pub_raw = _raw_pub(priv)
    canonical = build_signing_key_challenge_canonical("nonce-1", pub_raw)
    sig = priv.sign(canonical)
    assert verify_signature(priv.public_key(), canonical, sig) is True


@pytest.mark.unit
def test_pop_verify_rejects_tampered_sig_wrong_key_wrong_nonce_and_swapped_pubkey() -> None:
    priv = Ed25519PrivateKey.generate()
    pub_raw = _raw_pub(priv)
    canonical = build_signing_key_challenge_canonical("nonce-1", pub_raw)
    sig = priv.sign(canonical)

    # tampered signature
    bad = bytearray(sig)
    bad[0] ^= 0x01
    assert verify_signature(priv.public_key(), canonical, bytes(bad)) is False

    # wrong key
    other = Ed25519PrivateKey.generate()
    assert verify_signature(other.public_key(), canonical, sig) is False

    # wrong nonce — signature was over nonce-1, verify against nonce-2 canonical
    canon_n2 = build_signing_key_challenge_canonical("nonce-2", pub_raw)
    assert verify_signature(priv.public_key(), canon_n2, sig) is False

    # swapped pubkey under the same nonce — the canonical now binds a DIFFERENT
    # key, so the original signature no longer verifies (MITM key-swap defense).
    swapped_raw = _raw_pub(other)
    canon_swapped = build_signing_key_challenge_canonical("nonce-1", swapped_raw)
    assert verify_signature(priv.public_key(), canon_swapped, sig) is False


@pytest.mark.unit
def test_load_ed25519_public_key_roundtrips_valid_key() -> None:
    priv = Ed25519PrivateKey.generate()
    raw = _raw_pub(priv)
    loaded = load_ed25519_public_key(raw)
    assert loaded is not None
    assert fingerprint(loaded) == fingerprint(priv.public_key())


@pytest.mark.unit
def test_load_ed25519_public_key_rejects_malformed() -> None:
    assert load_ed25519_public_key(b"too-short") is None  # wrong length
    assert load_ed25519_public_key(b"\x00" * 33) is None  # one byte too long
    assert load_ed25519_public_key("not-bytes") is None  # type: ignore[arg-type]
    assert load_ed25519_public_key(None) is None  # type: ignore[arg-type]


@pytest.mark.unit
def test_load_ed25519_public_key_rejects_small_order_keys() -> None:
    """Small-order points (the all-zeros key et al.) are rejected at LOAD.

    A signature over a low-order key verifies WITHOUT the private half, so
    proof-of-possession cannot defend against them — they must never become a
    registered verifying key."""
    assert load_ed25519_public_key(b"\x00" * 32) is None  # the identity / all-zeros key
    assert (
        load_ed25519_public_key(
            bytes.fromhex("0100000000000000000000000000000000000000000000000000000000000000")
        )
        is None
    )


# --- PHASE-4 algebraic small-order / canonical-encoding gate -------------
#
# Regression for the proven auth-boundary bypass: the prior hardcoded
# byte-set missed these NON-CANONICAL identity encodings, against which a
# reviewer forged ``R=identity ‖ S=0`` EYENET-SIG-v1 signatures that verified.
# The algebraic gate (canonical ``y < p`` + ``8*P == identity``) is the
# backend-independent fix.

# The two encodings the reviewer proved bypass the loader (both encode
# y ≡ 1 mod p NON-CANONICALLY — high bit set / y = p+1).
_PROVEN_BYPASS_VECTORS = (
    bytes.fromhex("0100000000000000000000000000000000000000000000000000000000000080"),
    bytes.fromhex("eeffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"),
)

# The canonical Ed25519 small-order point table (libsodium / RFC 8032): the
# identity, the (0, ±i) order-4 points, and the order-2/order-8 points, with
# their high-bit-set variants. EVERY one must be rejected.
_CANONICAL_SMALL_ORDER = (
    "0100000000000000000000000000000000000000000000000000000000000000",  # identity
    "0000000000000000000000000000000000000000000000000000000000000000",  # y=0
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",  # y=-1 (order 2)
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",  # order 8
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85",  # variant
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",  # order 8
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa",  # variant
)


@pytest.mark.unit
@pytest.mark.parametrize("vector", _PROVEN_BYPASS_VECTORS)
def test_load_rejects_proven_noncanonical_identity_bypass(vector: bytes) -> None:
    """REGRESSION: the two reviewer-proven non-canonical identity encodings
    that the old hardcoded byte-set missed must be rejected at the loader."""
    assert load_ed25519_public_key(vector) is None


@pytest.mark.unit
@pytest.mark.parametrize("hex_key", _CANONICAL_SMALL_ORDER)
def test_load_rejects_full_canonical_small_order_set(hex_key: str) -> None:
    """ALL eight canonical small-order point encodings → None via the
    algebraic ``8*P == identity`` gate, not an enumerated byte-set."""
    assert load_ed25519_public_key(bytes.fromhex(hex_key)) is None


@pytest.mark.unit
def test_load_rejects_noncanonical_y_geq_p() -> None:
    """A 32-byte value whose decoded ``y >= p`` is a non-canonical encoding
    and must be rejected by the canonical-encoding gate."""
    # y = p (0xed..7f) and y = p+something; high-bit-clear so it is purely the
    # y >= p condition that rejects, not the x-sign bit.
    assert (
        load_ed25519_public_key(
            bytes.fromhex("edffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f")
        )
        is None
    )
    # All-0xff: y after masking the top bit is far above p.
    assert load_ed25519_public_key(b"\xff" * 32) is None


@pytest.mark.unit
def test_load_rejects_off_curve_point() -> None:
    """A 32-byte value that decodes to a ``y`` with no valid ``x`` on the
    curve (x^2 is a quadratic non-residue) → None."""
    # Search for a y < p that is off-curve (no modular sqrt for x^2).
    p = 2**255 - 19
    d = (-121665 * pow(121666, p - 2, p)) % p
    found = None
    for y in range(2, 5000):
        y2 = (y * y) % p
        x2 = ((y2 - 1) * pow((d * y2 + 1) % p, p - 2, p)) % p
        # Euler's criterion: x2 is a QR iff x2^((p-1)/2) == 1.
        if pow(x2, (p - 1) // 2, p) != 1 and x2 != 0:
            found = y
            break
    assert found is not None, "expected an off-curve y in range"
    raw = (found & ((1 << 255) - 1)).to_bytes(32, "little")
    assert load_ed25519_public_key(raw) is None


@pytest.mark.unit
def test_load_accepts_many_generated_keys_and_they_verify() -> None:
    """No false-positive rejection of legitimately generated keys: loop ~20,
    each must load AND a real signature over a challenge canonical must verify."""
    for _ in range(20):
        priv = Ed25519PrivateKey.generate()
        raw = _raw_pub(priv)
        loaded = load_ed25519_public_key(raw)
        assert loaded is not None
        assert fingerprint(loaded) == fingerprint(priv.public_key())
        canonical = build_canonical(*_FIELDS)
        assert verify_signature(loaded, canonical, priv.sign(canonical)) is True
