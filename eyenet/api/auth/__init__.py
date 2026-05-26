# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public surface of `eyenet.api.auth`.

Implementation lives in underscore-prefixed modules
([[feedback_underscore_prefix_internal_modules]]); this `__init__`
re-exports the names that the rest of the codebase is allowed to depend on.
"""

from __future__ import annotations

from ._cache import AuthCache, AuthContext
from ._jwt import (
    ACCESS_TTL,
    REFRESH_TTL,
    AccessClaims,
    JwtError,
    SigningKey,
    VerifyingKey,
    decode_access_token,
    hash_refresh_secret,
    load_signing_keypair,
    load_verifying_keys,
    mint_access_token,
    mint_refresh_secret,
)
from ._mfa import generate_secret, provisioning_uri, verify_code
from ._mfa_key import MfaKeyError, decrypt_secret, encrypt_secret, load_mfa_key
from ._passwords import hash_password, verify_password
from ._permissions import ROLE_BASELINE, resolve_effective_scopes

__all__ = [
    "ACCESS_TTL",
    "REFRESH_TTL",
    "ROLE_BASELINE",
    "AccessClaims",
    "AuthCache",
    "AuthContext",
    "JwtError",
    "MfaKeyError",
    "SigningKey",
    "VerifyingKey",
    "decode_access_token",
    "decrypt_secret",
    "encrypt_secret",
    "generate_secret",
    "hash_password",
    "hash_refresh_secret",
    "load_mfa_key",
    "load_signing_keypair",
    "load_verifying_keys",
    "mint_access_token",
    "mint_refresh_secret",
    "provisioning_uri",
    "resolve_effective_scopes",
    "verify_code",
    "verify_password",
]
