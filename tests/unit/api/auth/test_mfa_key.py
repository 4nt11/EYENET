"""Unit tests for the Fernet TOTP-secret encryption in ``_mfa_key``."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from eyenet.api.auth._mfa_key import (
    MfaKeyError,
    decrypt_secret,
    encrypt_secret,
    load_mfa_key,
)


@pytest.mark.unit
def test_load_mfa_key_autogenerates_on_first_call(tmp_path: Path) -> None:
    fernet = load_mfa_key(tmp_path)
    assert isinstance(fernet, Fernet)
    key_path = tmp_path / "jwt" / "mfa_key"
    assert key_path.exists()


@pytest.mark.unit
def test_load_mfa_key_file_is_0600(tmp_path: Path) -> None:
    load_mfa_key(tmp_path)
    key_path = tmp_path / "jwt" / "mfa_key"
    mode = stat.S_IMODE(key_path.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


@pytest.mark.unit
def test_load_mfa_key_is_idempotent(tmp_path: Path) -> None:
    first = load_mfa_key(tmp_path)
    bytes_before = (tmp_path / "jwt" / "mfa_key").read_bytes()
    second = load_mfa_key(tmp_path)
    bytes_after = (tmp_path / "jwt" / "mfa_key").read_bytes()
    assert bytes_before == bytes_after
    # Both Fernet instances must decrypt each other's ciphertext.
    ct = encrypt_secret(first, "JBSWY3DPEHPK3PXP")
    assert decrypt_secret(second, ct) == "JBSWY3DPEHPK3PXP"


@pytest.mark.unit
def test_encrypt_decrypt_round_trip(tmp_path: Path) -> None:
    fernet = load_mfa_key(tmp_path)
    plaintext = "JBSWY3DPEHPK3PXP"
    ct = encrypt_secret(fernet, plaintext)
    assert ct != plaintext
    assert decrypt_secret(fernet, ct) == plaintext


@pytest.mark.unit
def test_decrypt_with_wrong_key_raises(tmp_path: Path) -> None:
    fernet_a = load_mfa_key(tmp_path / "a")
    fernet_b = load_mfa_key(tmp_path / "b")
    ct = encrypt_secret(fernet_a, "JBSWY3DPEHPK3PXP")
    with pytest.raises(MfaKeyError, match="invalid_or_tampered_ciphertext"):
        decrypt_secret(fernet_b, ct)


@pytest.mark.unit
def test_decrypt_tampered_ciphertext_raises(tmp_path: Path) -> None:
    fernet = load_mfa_key(tmp_path)
    ct = encrypt_secret(fernet, "JBSWY3DPEHPK3PXP")
    tampered = ct[:-4] + ("AAAA" if ct[-4:] != "AAAA" else "BBBB")
    with pytest.raises(MfaKeyError):
        decrypt_secret(fernet, tampered)
