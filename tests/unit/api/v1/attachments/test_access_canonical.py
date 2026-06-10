# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the §5.6 acknowledgment body-hash helper (PHASE-5).

`compute_access_body_hash` defines the EXACT preimage a client signs over. The
tests pin three properties that the binding relies on:

  * determinism — same body (key order irrelevant) → same hash;
  * signature-exclusion — adding/removing ``operator_signature`` never changes
    the hash (it is the output, never an input);
  * tamper-sensitivity — changing any signed field changes the hash;
  * the canonical reconstruction matches a real client-side Ed25519 sign.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from eyenet.api.v1.attachments._access_canonical import compute_access_body_hash
from eyenet.crypto import build_canonical, fingerprint, verify_signature

pytestmark = pytest.mark.unit

_NONCE = UUID("11111111-1111-1111-1111-111111111111")
_CONTENT_HASH = "a" * 64


def _body() -> dict[str, object]:
    return {
        "access_nonce": _NONCE,
        "expected_content_hash": _CONTENT_HASH,
        "request_id": "req-001",
        "signed_at": datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC),
        "reason": "reviewing evidence for case",
        "viewing_context": "case=APT-29",
        "case_refs": [UUID("22222222-2222-2222-2222-222222222222")],
    }


def test_deterministic_regardless_of_key_order() -> None:
    body = _body()
    reordered = dict(reversed(list(body.items())))
    assert compute_access_body_hash(body) == compute_access_body_hash(reordered)


def test_operator_signature_is_excluded() -> None:
    body = _body()
    without = compute_access_body_hash(body)
    with_sig = compute_access_body_hash({**body, "operator_signature": "ed25519:" + "A" * 86})
    assert without == with_sig


def test_tampering_any_signed_field_changes_hash() -> None:
    base = compute_access_body_hash(_body())
    for key, mutated in (
        ("reason", "totally different justification text"),
        ("viewing_context", "case=OTHER"),
        ("request_id", "req-002"),
        ("expected_content_hash", "b" * 64),
    ):
        body = _body()
        body[key] = mutated
        assert compute_access_body_hash(body) != base, key
    # case_refs order is signed too.
    body = _body()
    body["case_refs"] = [UUID("33333333-3333-3333-3333-333333333333")]
    assert compute_access_body_hash(body) != base


def test_canonical_reconstruction_matches_client_sign() -> None:
    """A client signs build_canonical(...); the server rebuilds the same bytes."""
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    body = _body()

    # Client side: compute body hash, build the §5.7 canonical, sign it.
    body_hash = compute_access_body_hash(body)
    url = "/v1/attachments/44444444-4444-4444-4444-444444444444/access"
    canonical = build_canonical(
        "POST",
        url,
        str(body["request_id"]),
        body["signed_at"].isoformat(),  # type: ignore[union-attr]
        body_hash,
        _CONTENT_HASH,
    )
    signature = private.sign(canonical)

    # Server side: identical reconstruction verifies.
    server_canonical = build_canonical(
        "POST",
        url,
        str(body["request_id"]),
        body["signed_at"].isoformat(),  # type: ignore[union-attr]
        compute_access_body_hash(body),
        _CONTENT_HASH,
    )
    assert verify_signature(public, server_canonical, signature) is True
    # A tampered reason breaks verification (body hash feeds the canonical).
    tampered = {**body, "reason": "an entirely different reason string"}
    bad_canonical = build_canonical(
        "POST",
        url,
        str(body["request_id"]),
        body["signed_at"].isoformat(),  # type: ignore[union-attr]
        compute_access_body_hash(tampered),
        _CONTENT_HASH,
    )
    assert verify_signature(public, bad_canonical, signature) is False
    # fingerprint is reproducible (sanity — server resolves it, no client kid).
    assert len(fingerprint(public)) == 16
