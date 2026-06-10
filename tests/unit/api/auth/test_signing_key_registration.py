# SPDX-License-Identifier: AGPL-3.0-or-later
"""PHASE-4 register_operator_signing_key — pure proof-of-possession seam."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from eyenet.api.v1.auth._signing_key_registration import (
    SigningKeyRegistrationError,
    register_operator_signing_key,
)
from eyenet.crypto import build_signing_key_challenge_canonical
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _raw_pub(priv: Ed25519PrivateKey) -> bytes:
    return priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


async def _mint_and_sign(
    storage: BaseRepository, user_id, priv: Ed25519PrivateKey
) -> tuple[bytes, object, bytes]:
    pub_raw = _raw_pub(priv)
    nonce = await storage.mint_signing_key_challenge(user_id, now=_NOW)
    sig = priv.sign(build_signing_key_challenge_canonical(str(nonce), pub_raw))
    return pub_raw, nonce, sig


@pytest.mark.unit
@pytest.mark.asyncio
async def test_happy_path_registers_and_resolves(storage: BaseRepository) -> None:
    user_id = uuid4()
    priv = Ed25519PrivateKey.generate()
    pub_raw, nonce, sig = await _mint_and_sign(storage, user_id, priv)

    fp = await register_operator_signing_key(
        storage,
        user_id=user_id,
        public_key_bytes=pub_raw,
        challenge_nonce=nonce,
        challenge_signature=sig,
        now=_NOW,
    )
    assert len(fp) == 16
    resolved = await storage.lookup_key_for_user(user_id, fp)
    assert resolved is not None
    assert resolved[0] == pub_raw


@pytest.mark.unit
@pytest.mark.asyncio
async def test_malformed_pubkey_raises_and_records_nothing(storage: BaseRepository) -> None:
    user_id = uuid4()
    nonce = await storage.mint_signing_key_challenge(user_id, now=_NOW)
    with pytest.raises(SigningKeyRegistrationError) as exc:
        await register_operator_signing_key(
            storage,
            user_id=user_id,
            public_key_bytes=b"\x01" * 31,  # wrong length
            challenge_nonce=nonce,
            challenge_signature=b"\x00" * 64,
            now=_NOW,
        )
    assert exc.value.reason == "malformed_public_key"
    # Nonce NOT consumed (verify failed before consume) — still usable.
    assert await storage.consume_signing_key_challenge(nonce, user_id, now=_NOW) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_all_zeros_pubkey_rejected_at_load(storage: BaseRepository) -> None:
    """An all-zeros key is a small-order point: a signature over it verifies
    WITHOUT the private half, so it must be rejected at LOAD (before PoP) —
    otherwise an attacker registers a key they never possessed. Register
    nothing; the nonce is not even reached."""
    user_id = uuid4()
    nonce = await storage.mint_signing_key_challenge(user_id, now=_NOW)
    with pytest.raises(SigningKeyRegistrationError) as exc:
        await register_operator_signing_key(
            storage,
            user_id=user_id,
            public_key_bytes=b"\x00" * 32,
            challenge_nonce=nonce,
            challenge_signature=b"\x00" * 64,
            now=_NOW,
        )
    assert exc.value.reason == "malformed_public_key"
    # Nonce untouched (load failed before consume).
    assert await storage.consume_signing_key_challenge(nonce, user_id, now=_NOW) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_pop_raises_and_records_nothing(storage: BaseRepository) -> None:
    user_id = uuid4()
    priv = Ed25519PrivateKey.generate()
    pub_raw, nonce, sig = await _mint_and_sign(storage, user_id, priv)
    bad_sig = bytearray(sig)
    bad_sig[0] ^= 0x01
    with pytest.raises(SigningKeyRegistrationError) as exc:
        await register_operator_signing_key(
            storage,
            user_id=user_id,
            public_key_bytes=pub_raw,
            challenge_nonce=nonce,
            challenge_signature=bytes(bad_sig),
            now=_NOW,
        )
    assert exc.value.reason == "proof_of_possession_failed"
    # Nonce not burned by a failed proof.
    assert await storage.consume_signing_key_challenge(nonce, user_id, now=_NOW) is True
    # Nothing registered.
    fp = fingerprint_of(pub_raw)
    assert await storage.lookup_key_for_user(user_id, fp) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_consumed_nonce_raises_challenge_unusable(storage: BaseRepository) -> None:
    user_id = uuid4()
    priv = Ed25519PrivateKey.generate()
    pub_raw, nonce, sig = await _mint_and_sign(storage, user_id, priv)
    # Pre-consume the nonce so registration's consume sees zero rows.
    assert await storage.consume_signing_key_challenge(nonce, user_id, now=_NOW) is True
    with pytest.raises(SigningKeyRegistrationError) as exc:
        await register_operator_signing_key(
            storage,
            user_id=user_id,
            public_key_bytes=pub_raw,
            challenge_nonce=nonce,
            challenge_signature=sig,
            now=_NOW,
        )
    assert exc.value.reason == "challenge_unusable"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wrong_user_nonce_raises_challenge_unusable(storage: BaseRepository) -> None:
    minter = uuid4()
    attacker = uuid4()
    priv = Ed25519PrivateKey.generate()
    pub_raw, nonce, sig = await _mint_and_sign(storage, minter, priv)
    # Attacker (different authenticated identity) presents minter's nonce with
    # a valid PoP over their own key — the user-bound consume rejects it.
    with pytest.raises(SigningKeyRegistrationError) as exc:
        await register_operator_signing_key(
            storage,
            user_id=attacker,
            public_key_bytes=pub_raw,
            challenge_nonce=nonce,
            challenge_signature=sig,
            now=_NOW,
        )
    assert exc.value.reason == "challenge_unusable"


# The two reviewer-proven non-canonical identity encodings: an attacker
# submits one of these as the "verifying key" alongside the forged
# ``R = canonical-identity ‖ S = 0`` proof-of-possession signature. The
# algebraic loader gate must REJECT the key BEFORE proof-of-possession, so no
# key NOBODY controls is ever recorded against the user.
_FORGED_R = bytes.fromhex("0100000000000000000000000000000000000000000000000000000000000080")
_FORGED_S = b"\x00" * 32
_FORGED_SIG = _FORGED_R + _FORGED_S
_PROVEN_BYPASS_VECTORS = (
    bytes.fromhex("0100000000000000000000000000000000000000000000000000000000000080"),
    bytes.fromhex("eeffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"),
)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("vector", _PROVEN_BYPASS_VECTORS)
async def test_forged_smallorder_key_rejected_at_register_seam(
    storage: BaseRepository, vector: bytes
) -> None:
    """END-TO-END bypass closure: registering a proven non-canonical-identity
    key with the forged ``R=identity ‖ S=0`` signature is rejected at LOAD
    (``malformed_public_key``), records NO key, and never reaches the nonce."""
    user_id = uuid4()
    nonce = await storage.mint_signing_key_challenge(user_id, now=_NOW)
    with pytest.raises(SigningKeyRegistrationError) as exc:
        await register_operator_signing_key(
            storage,
            user_id=user_id,
            public_key_bytes=vector,
            challenge_nonce=nonce,
            challenge_signature=_FORGED_SIG,
            now=_NOW,
        )
    assert exc.value.reason == "malformed_public_key"
    # No verifying key was recorded for the attacker's chosen forgeable key.
    assert await storage.active_signing_key_for(user_id) is None
    # The nonce was never consumed (load failed before consume) — still usable.
    assert await storage.consume_signing_key_challenge(nonce, user_id, now=_NOW) is True


def fingerprint_of(public_key_bytes: bytes) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from eyenet.crypto import fingerprint

    return fingerprint(Ed25519PublicKey.from_public_bytes(public_key_bytes))
