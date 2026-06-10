# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ed25519 verification primitives for the file-access journal (API_PLAN §5.7).

VERIFICATION ONLY — the public-key side. No private key, no signing, no
key generation lives here (that is B2/B3). EYENET reconstructs the
canonical request form, looks up the operator's verifying key by
fingerprint, and verifies the detached signature.

Three primitives:

* :func:`fingerprint` — the 16-hex ``kid`` carried on the wire. Defined as
  the first 8 bytes of ``sha256(DER SubjectPublicKeyInfo)`` of the public
  key, hex-encoded. The DER encoding is fixed (RFC 8410
  SubjectPublicKeyInfo), so the fingerprint is reproducible from the raw
  32-byte key alone.

* :func:`build_canonical` — the ``EYENET-SIG-v1`` signing string. Uses
  **length-prefixed framing** (see below) so the field set is unambiguous:
  no separator a caller can smuggle into a field (a URL legitimately
  contains ``|``, ``\\n``, etc.). Two distinct field-tuples can NEVER
  produce the same canonical bytes.

* :func:`verify_signature` — detached Ed25519 verify; returns ``False`` on
  :class:`InvalidSignature` (the exact exception is caught — no bare
  except, no crash).
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey,
    )

# Versioned domain-separation tag. Bump if the framing ever changes so an
# old-format signature can never be replayed against a new verifier.
_SIG_SCHEME = b"EYENET-SIG-v1"
_FINGERPRINT_BYTES = 8


def _der_spki(verifying_key: Ed25519PublicKey) -> bytes:
    """DER-encoded SubjectPublicKeyInfo bytes for the public key.

    RFC 8410 fixes this encoding, so the same 32-byte Ed25519 key always
    yields the same DER bytes (and therefore the same fingerprint).
    """
    return verifying_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def fingerprint(verifying_key: Ed25519PublicKey) -> str:
    """Return the 16-hex key fingerprint (``kid``).

    ``sha256(DER SubjectPublicKeyInfo)`` truncated to the first 8 bytes,
    hex-encoded → 16 lowercase hex chars.
    """
    digest = hashlib.sha256(_der_spki(verifying_key)).digest()
    return digest[:_FINGERPRINT_BYTES].hex()


def _frame_bytes(raw: bytes) -> bytes:
    """Length-prefixed encoding of a raw byte string.

    ``len(raw)`` as a 4-byte big-endian unsigned integer, followed by the
    bytes. Because the reader always consumes exactly the declared length,
    no byte sequence inside an element (``|``, newline, NUL) can be
    mistaken for a delimiter or made to look like the start of the next
    element. The concatenation of framed elements is therefore an
    injective function of the ordered element tuple.
    """
    return len(raw).to_bytes(4, "big") + raw


def _frame(field: str) -> bytes:
    """Length-prefixed encoding of one UTF-8 field (see :func:`_frame_bytes`)."""
    return _frame_bytes(field.encode("utf-8"))


def build_canonical(
    method: str,
    url: str,
    request_id: str,
    timestamp: str,
    body_hash: str,
    content_hash: str,
) -> bytes:
    """Build the ``EYENET-SIG-v1`` canonical signing bytes (§5.7).

    Framing: the scheme tag is ITSELF length-prefixed (same 4-byte
    big-endian framing as the fields), then each field length-prefixed,
    concatenated in fixed order. Framing the scheme tag makes injectivity
    STRUCTURAL rather than dependent on the tag being a fixed-length
    constant: a future ``EYENET-SIG-v2`` of a different length can never
    produce bytes that collide with a v1 string, because the leading
    length word disambiguates the boundary. This domain-separates the
    signing string from any other Ed25519 use of the same operator key.

    Injection-proof: because every element (scheme tag included) is
    preceded by its exact byte length, an element that ends mid-value
    cannot run into the next, and a value containing the delimiter
    characters of a naive ``|``-join cannot forge an alternate parse. Two
    distinct ``(method, url, request_id, timestamp, body_hash,
    content_hash)`` tuples always yield distinct canonical bytes.
    """
    return _frame_bytes(_SIG_SCHEME) + b"".join(
        _frame(field) for field in (method, url, request_id, timestamp, body_hash, content_hash)
    )


# Domain-separation tag for the JOURNAL-ROW canonical serialization. This is
# DISTINCT from ``_SIG_SCHEME`` (the operator-signed request form): the
# journal-row canonical feeds ``self_hash`` (the chain), NOT signature
# verification. A separate tag guarantees a row-hash preimage can never collide
# with a signing-string preimage even if the field bytes overlap.
_JOURNAL_ROW_SCHEME = b"EYENET-FAJ-v1"


def build_journal_row_canonical(
    *,
    access_id: bytes,
    audit_event_id: bytes,
    user_id: bytes,
    grant_id: bytes,
    content_hash: bytes,
    content_size: int,
    content_mime: str,
    tier: str,
    served_at: str,
    served_via: str,
    acknowledgment_id: bytes,
    operator_signature: bytes,
    signing_pubkey_fingerprint: str,
) -> bytes:
    """Injection-proof length-prefixed serialization of a journal row's identity.

    The ``self_hash`` of a :class:`FileAccessJournalTable` row is
    ``sha256(build_journal_row_canonical(...) || prev_journal_hash)``. Every
    field is length-prefixed (``_frame_bytes`` framing) so no field value —
    a mime string, a signature blob — can be made to look like an adjacent
    field, exactly as the request-signing canonical is injection-proof.

    Optional UUID fields (``audit_event_id``, ``grant_id``,
    ``acknowledgment_id``) are passed as their raw 16 bytes when present and as
    a zero-length frame (``b""``) when absent — the length prefix distinguishes
    a present-empty from an absent field unambiguously.
    """
    return _frame_bytes(_JOURNAL_ROW_SCHEME) + b"".join(
        (
            _frame_bytes(access_id),
            _frame_bytes(audit_event_id),
            _frame_bytes(user_id),
            _frame_bytes(grant_id),
            _frame_bytes(content_hash),
            _frame(str(content_size)),
            _frame(content_mime),
            _frame(tier),
            _frame(served_at),
            _frame(served_via),
            _frame_bytes(acknowledgment_id),
            _frame_bytes(operator_signature),
            _frame(signing_pubkey_fingerprint),
        )
    )


# Domain-separation tag for the operator SIGNING-KEY-REGISTRATION proof of
# possession (PHASE-4). DISTINCT from both ``_SIG_SCHEME`` (the per-request
# operator signature) and ``_JOURNAL_ROW_SCHEME`` (the chain row hash): a
# registration-challenge signature must NEVER be replayable as a file-access
# request signature, nor collide with a journal-row hash preimage, even though
# the same operator key signs in all three contexts. The framed tag (its own
# length prefix) makes that separation structural, not length-dependent.
_SIGNING_KEY_CHALLENGE_SCHEME = b"EYENET-SIGNING-KEY-CHALLENGE-v1"

_ED25519_PUBLIC_KEY_LEN = 32


def build_signing_key_challenge_canonical(nonce: str, public_key_bytes: bytes) -> bytes:
    """Build the ``EYENET-SIGNING-KEY-CHALLENGE-v1`` proof-of-possession bytes.

    The operator signs these bytes with the PRIVATE key matching
    ``public_key_bytes`` to prove possession during self-service registration
    (PHASE-4). Binds BOTH the server-minted ``nonce`` AND the submitted public
    key:

    * Binding the nonce makes the proof single-use and unforgeable ahead of
      time (the operator cannot pre-sign for a nonce it has not been issued).
    * Binding the public key defeats a man-in-the-middle key swap: a captured
      valid ``(nonce, signature)`` cannot be re-presented under a DIFFERENT
      ``public_key_bytes`` — the canonical, and therefore the signature, would
      not match. The signature is verified AGAINST the submitted key, so an
      attacker who swaps the key necessarily invalidates the proof.

    Length-prefixed framing (``_frame_bytes``) with a framed domain tag, so the
    serialization is injective and domain-separated from every other Ed25519
    use of the same key — identical guarantees to :func:`build_canonical`.
    """
    return _frame_bytes(_SIGNING_KEY_CHALLENGE_SCHEME) + b"".join(
        (
            _frame(nonce),
            _frame_bytes(public_key_bytes),
        )
    )


# --- Ed25519 curve constants (RFC 8032 §5.1) -----------------------------
#
# Edwards25519 over GF(p), p = 2**255 - 19, curve equation
# ``-x^2 + y^2 = 1 + d*x^2*y^2``. These are the ONLY constants the
# pure-Python point decode below needs — no secret material, so the
# arithmetic is plain (non-constant-time) ``int`` math: this validates a
# PUBLIC key, correctness is the requirement, not timing resistance.
_ED25519_P = 2**255 - 19
# d = -121665 / 121666 (mod p)
_ED25519_D = (-121665 * pow(121666, _ED25519_P - 2, _ED25519_P)) % _ED25519_P
# sqrt(-1) = 2**((p-1)//4) (mod p), used to fix the modular square-root branch.
_ED25519_SQRT_M1 = pow(2, (_ED25519_P - 1) // 4, _ED25519_P)


def _decode_ed25519_point(raw: bytes) -> tuple[int, int] | None:
    """Decode a 32-byte Ed25519 public key to its affine point, or ``None``.

    Pure RFC 8032 §5.1.3 point decompression — no dependency exposes Edwards
    point ops, so the math lives here. Returns ``None`` (REJECT) for any input
    that is not a CANONICALLY-encoded on-curve point:

    * ``y >= p`` after clearing the x-sign bit — a NON-CANONICAL encoding (the
      reduction is not unique; both proven bypass vectors land here).
    * no modular square root for ``x^2`` — the point is OFF the curve.
    * ``x == 0`` with the sign bit set — non-canonical encoding of ``(0, y)``.

    The returned ``(x, y)`` is the curve point; the caller still applies the
    algebraic small-order (8-torsion) gate before trusting it.
    """
    p = _ED25519_P
    y = int.from_bytes(raw, "little")
    sign = (y >> 255) & 1
    y &= (1 << 255) - 1
    # Canonical-encoding gate — the complete, backend-independent defense
    # against the proven non-canonical-identity vectors.
    if y >= p:
        return None
    # Recover x^2 = (y^2 - 1) / (d*y^2 + 1)  (mod p).
    y2 = (y * y) % p
    u = (y2 - 1) % p
    v = (_ED25519_D * y2 + 1) % p
    x2 = (u * pow(v, p - 2, p)) % p
    # Modular square root: candidate, then the sqrt(-1) branch, else off-curve.
    x = pow(x2, (p + 3) // 8, p)
    if (x * x - x2) % p != 0:
        x = (x * _ED25519_SQRT_M1) % p
    if (x * x - x2) % p != 0:
        return None
    if x == 0 and sign == 1:
        return None
    if (x & 1) != sign:
        x = (p - x) % p
    return (x, y)


def _ed25519_is_small_order(point: tuple[int, int]) -> bool:
    """Return ``True`` iff ``point`` lies in the 8-torsion subgroup.

    Computes ``8 * point`` via three Edwards doublings in extended
    (projective) coordinates and tests equality with the neutral element
    ``(0, 1)`` (i.e. ``X == 0 and Y == Z`` projectively). A point of order
    dividing 8 is annihilated by multiplication-by-8 → the identity. This
    catches ALL small-order points (the identity and the other seven),
    independent of the backend's encoding quirks.
    """
    p = _ED25519_P
    d2 = (2 * _ED25519_D) % p
    x, y = point
    # Extended coordinates (X, Y, Z, T) with Z = 1, T = x*y.
    state = (x % p, y % p, 1, (x * y) % p)

    def _double(pt: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x1, y1, z1, t1 = pt
        a = ((y1 - x1) * (y1 - x1)) % p
        b = ((y1 + x1) * (y1 + x1)) % p
        c = (t1 * d2 * t1) % p
        e_ = (2 * z1 * z1) % p
        # Unified add of pt with itself; expressed via the add identities.
        # f = D - C, g = D + C, h = B + A, e = B - A  (with D=e_).
        e = (b - a) % p
        f = (e_ - c) % p
        g = (e_ + c) % p
        h = (b + a) % p
        return ((e * f) % p, (g * h) % p, (f * g) % p, (e * h) % p)

    state = _double(_double(_double(state)))
    big_x, big_y, big_z, _big_t = state
    return big_x % p == 0 and (big_y - big_z) % p == 0


def load_ed25519_public_key(public_key_bytes: object) -> Ed25519PublicKey | None:
    """Safely load a raw Ed25519 public key, or ``None`` on any malformed/unsafe input.

    Returns the :class:`Ed25519PublicKey` only for a well-formed 32-byte raw
    key that is CANONICALLY encoded, ON the curve, and NOT a small-order
    point. A non-bytes value, a wrong-length blob, a non-canonical encoding, an
    off-curve value, a small-order point, or bytes the backend rejects (the
    EXACT :class:`ValueError` is caught — no bare except, no crash) all return
    ``None`` so the registration path can fail closed.

    The gate is ALGEBRAIC and backend-independent (the prior hardcoded
    byte-set was incomplete AND `cryptography`/openssl-version dependent — a
    reviewer forged signatures against non-canonical-identity encodings the set
    missed). The check, per RFC 8032 §5.1:

    1. exactly 32 bytes;
    2. canonical encoding — decoded ``y < p`` (kills the non-canonical-identity
       bypass vectors, both of which encode ``y ≡ 1 mod p`` non-canonically);
    3. on-curve — a modular square root for ``x^2`` exists;
    4. NOT small-order — ``8 * P != identity`` (catches every 8-torsion point,
       which is the property that makes a forged signature verify without the
       private half).

    Only after all four pass do we hand the ORIGINAL 32 bytes back to the
    library, so downstream :func:`verify_signature` is unchanged.
    """
    if not isinstance(public_key_bytes, (bytes, bytearray, memoryview)):
        return None
    raw = bytes(public_key_bytes)
    if len(raw) != _ED25519_PUBLIC_KEY_LEN:
        return None
    point = _decode_ed25519_point(raw)
    if point is None:
        return None
    if _ed25519_is_small_order(point):
        return None
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: PLC0415
        Ed25519PublicKey as _Ed25519PublicKey,
    )

    try:
        return _Ed25519PublicKey.from_public_bytes(raw)
    except ValueError:
        return None


def verify_signature(
    verifying_key: Ed25519PublicKey,
    canonical: object,
    signature: object,
) -> bool:
    """Verify a detached Ed25519 signature over ``canonical``.

    Returns ``True`` on a valid signature, ``False`` on an invalid one —
    including the natural shape of an ABSENT signature/canonical header,
    where ``signature`` or ``canonical`` arrives as ``None`` or some other
    non-bytes value. Such inputs are treated as invalid (``False``), never
    raised: the B3 verify caller must not crash on a missing header.

    Only the exact :class:`InvalidSignature` raised by the backend is
    caught for the cryptographic-mismatch case; no broader exception is
    swallowed.
    """
    # An absent or malformed header is INVALID, not an exception. Guard
    # before touching the backend, which would raise ``TypeError`` on a
    # non-bytes argument.
    if not isinstance(signature, (bytes, bytearray, memoryview)) or not isinstance(
        canonical, (bytes, bytearray, memoryview)
    ):
        return False
    try:
        verifying_key.verify(bytes(signature), bytes(canonical))
    except InvalidSignature:
        return False
    return True


__all__ = [
    "build_canonical",
    "build_journal_row_canonical",
    "build_signing_key_challenge_canonical",
    "fingerprint",
    "load_ed25519_public_key",
    "verify_signature",
]
