# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the §5.9 anchor Ed25519 signing helpers."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from eyenet.crypto import (
    build_anchor_canonical,
    load_anchor_key,
    load_or_create_deployment_id,
    verify_signature,
)

pytestmark = pytest.mark.unit


def _canonical():
    return build_anchor_canonical(
        deployment_id=uuid4(),
        anchor_seq=7,
        anchored_at=datetime.now(tz=UTC).isoformat(),
        audit_head="a" * 64,
        journal_head="b" * 64,
    )


def test_sign_then_verify_roundtrip(tmp_path) -> None:
    signer = load_anchor_key(tmp_path)
    canonical = _canonical()
    wire = signer.sign(canonical)
    assert wire.startswith("ed25519:")

    raw = base64.urlsafe_b64decode(wire.removeprefix("ed25519:"))
    pub = Ed25519PublicKey.from_public_bytes(signer.verifying_key_bytes)
    assert verify_signature(pub, canonical, raw) is True
    # a different canonical must not verify under the same signature.
    assert verify_signature(pub, _canonical(), raw) is False


def test_key_materialized_once(tmp_path) -> None:
    a = load_anchor_key(tmp_path)
    b = load_anchor_key(tmp_path)
    assert a.verifying_key_bytes == b.verifying_key_bytes
    assert (tmp_path / "jwt" / "anchor_ed25519.key").exists()


def test_deployment_id_is_stable(tmp_path) -> None:
    first = load_or_create_deployment_id(tmp_path)
    assert load_or_create_deployment_id(tmp_path) == first
