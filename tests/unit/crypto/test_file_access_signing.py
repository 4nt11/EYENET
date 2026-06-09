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

from eyenet.crypto import build_canonical, fingerprint, verify_signature

_FIELDS = ("GET", "/v1/files/abc?x=1", "req-123", "2026-06-09T12:00:00Z", "", "f" * 64)


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
