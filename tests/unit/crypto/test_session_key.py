"""Unit tests for the Fernet session-credential encryption in ``_session_key``."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from eyenet.crypto._session_key import (
    SessionKeyError,
    decrypt_session,
    encrypt_session,
    load_session_key,
)

_SAMPLE = "1BVdummyStringSessionblob=="


@pytest.mark.unit
def test_load_session_key_autogenerates_on_first_call(tmp_path: Path) -> None:
    fernet = load_session_key(tmp_path)
    assert isinstance(fernet, Fernet)
    assert (tmp_path / "jwt" / "session_fernet.key").exists()


@pytest.mark.unit
def test_load_session_key_file_is_0600(tmp_path: Path) -> None:
    load_session_key(tmp_path)
    key_path = tmp_path / "jwt" / "session_fernet.key"
    mode = stat.S_IMODE(key_path.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


@pytest.mark.unit
def test_load_session_key_is_idempotent(tmp_path: Path) -> None:
    first = load_session_key(tmp_path)
    bytes_before = (tmp_path / "jwt" / "session_fernet.key").read_bytes()
    second = load_session_key(tmp_path)
    bytes_after = (tmp_path / "jwt" / "session_fernet.key").read_bytes()
    assert bytes_before == bytes_after
    # Both Fernet instances must decrypt each other's ciphertext.
    blob = encrypt_session(first, _SAMPLE)
    assert decrypt_session(second, blob) == _SAMPLE


@pytest.mark.unit
def test_encrypt_decrypt_round_trip(tmp_path: Path) -> None:
    fernet = load_session_key(tmp_path)
    blob = encrypt_session(fernet, _SAMPLE)
    assert isinstance(blob, bytes)
    assert _SAMPLE.encode() not in blob  # ciphertext must not embed the plaintext
    assert decrypt_session(fernet, blob) == _SAMPLE


@pytest.mark.unit
def test_decrypt_with_wrong_key_raises(tmp_path: Path) -> None:
    fernet_a = load_session_key(tmp_path / "a")
    fernet_b = load_session_key(tmp_path / "b")
    blob = encrypt_session(fernet_a, _SAMPLE)
    with pytest.raises(SessionKeyError, match="invalid_or_tampered_session_blob"):
        decrypt_session(fernet_b, blob)


@pytest.mark.unit
def test_decrypt_tampered_blob_raises(tmp_path: Path) -> None:
    fernet = load_session_key(tmp_path)
    blob = encrypt_session(fernet, _SAMPLE)
    tampered = blob[:-4] + (b"AAAA" if blob[-4:] != b"AAAA" else b"BBBB")
    with pytest.raises(SessionKeyError):
        decrypt_session(fernet, tampered)
