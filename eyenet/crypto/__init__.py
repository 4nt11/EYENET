# SPDX-License-Identifier: AGPL-3.0-or-later
"""EYENET cryptographic primitives.

Public surface is re-exported here; implementations live in
underscore-prefixed internal modules (PEP 8 public-vs-internal split).
"""

from __future__ import annotations

from ._exoneration_signing import (
    BY_USER_CONTENT_HASH_SENTINEL,
    ExonerationSigner,
    build_exoneration_canonical,
    load_exoneration_key,
)
from ._file_access_signing import (
    build_canonical,
    build_journal_row_canonical,
    build_signing_key_challenge_canonical,
    fingerprint,
    load_ed25519_public_key,
    verify_signature,
)

__all__ = [
    "BY_USER_CONTENT_HASH_SENTINEL",
    "ExonerationSigner",
    "build_canonical",
    "build_exoneration_canonical",
    "build_journal_row_canonical",
    "build_signing_key_challenge_canonical",
    "fingerprint",
    "load_ed25519_public_key",
    "load_exoneration_key",
    "verify_signature",
]
