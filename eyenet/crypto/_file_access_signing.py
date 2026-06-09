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
    "fingerprint",
    "verify_signature",
]
