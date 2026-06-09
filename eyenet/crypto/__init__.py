# SPDX-License-Identifier: AGPL-3.0-or-later
"""EYENET cryptographic primitives.

Public surface is re-exported here; implementations live in
underscore-prefixed internal modules (PEP 8 public-vs-internal split).
"""

from __future__ import annotations

from ._file_access_signing import (
    build_canonical,
    build_journal_row_canonical,
    build_signing_key_challenge_canonical,
    fingerprint,
    load_ed25519_public_key,
    verify_signature,
)

__all__ = [
    "build_canonical",
    "build_journal_row_canonical",
    "build_signing_key_challenge_canonical",
    "fingerprint",
    "load_ed25519_public_key",
    "verify_signature",
]
