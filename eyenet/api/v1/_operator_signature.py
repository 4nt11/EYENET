# SPDX-License-Identifier: AGPL-3.0-or-later
"""Decode the ``ed25519:<urlsafe-b64>`` operator-signature wire form to raw bytes.

Shared by the §5.6 file-access and §4.9 reclassify surfaces. A malformed prefix
or base64 payload is an auth-class failure (no oracle), never an unhandled crash.
"""

from __future__ import annotations

import base64
import binascii

from eyenet.api.deps import AuthError

_SIG_PREFIX = "ed25519:"
_ED25519_SIG_LEN = 64


def decode_operator_signature(operator_signature: str) -> bytes:
    """Decode ``ed25519:<urlsafe-b64>`` into 64 raw bytes, or raise ``AuthError``."""
    if not operator_signature.startswith(_SIG_PREFIX):
        raise AuthError("operator_signature_malformed_prefix")
    encoded = operator_signature[len(_SIG_PREFIX) :]
    try:
        raw = base64.urlsafe_b64decode(encoded)
    except (ValueError, binascii.Error) as exc:
        raise AuthError("operator_signature_b64_invalid") from exc
    if len(raw) != _ED25519_SIG_LEN:
        raise AuthError("operator_signature_length_invalid")
    return raw


__all__ = ["decode_operator_signature"]
