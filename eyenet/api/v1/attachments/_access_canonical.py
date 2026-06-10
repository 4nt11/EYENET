# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic acknowledgment-body hashing for the §5.6 file-access flow.

PHASE-5 binds the operator's Ed25519 signature to the *content* of the
acknowledgment body (not just the nonce + content hash). The operator signs
``build_canonical("POST", url, request_id, signed_at, body_hash, content_hash)``
where ``body_hash`` is the SHA-256 of the acknowledgment body with the
``operator_signature`` field EXCLUDED.

The single helper :func:`compute_access_body_hash` defines the EXACT
serialization so a server (verify) and any client (sign) compute byte-identical
hashes. Tamper with any signed field (``reason``, ``viewing_context``,
``case_refs``, ``access_nonce``, ``expected_content_hash``, ``request_id``,
``signed_at``) → the body hash changes → the signature fails to verify.

Canonical body-hash construction (DOCUMENTED CONTRACT — a client MUST match):

1. Start from the acknowledgment as a plain ``dict``.
2. REMOVE the ``operator_signature`` key entirely (it is the output, never an
   input to its own preimage).
3. Normalize value types to JSON-native, deterministic forms:
   - ``UUID`` → its canonical lowercase string (``str(uuid)``).
   - ``datetime`` → ISO-8601 via ``.isoformat()`` (tz-aware in/out preserved).
   - ``list`` of UUID (``case_refs``) → list of canonical lowercase strings,
     ORDER PRESERVED (the operator signs the order they submit).
   - ``None`` stays ``null``; ``str``/``int`` pass through unchanged.
4. Serialize with ``json.dumps(obj, sort_keys=True, separators=(",", ":"),
   ensure_ascii=False)`` — sorted keys, no insignificant whitespace, UTF-8.
5. ``body_hash = sha256(serialized.encode("utf-8")).hexdigest()`` (64 lowercase
   hex chars).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID


def _normalize(value: Any) -> Any:
    """Coerce one body value into a deterministic JSON-native form."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    return value


def compute_access_body_hash(payload_without_signature: dict[str, Any]) -> str:
    """Hex SHA-256 of the canonical acknowledgment body, signature EXCLUDED.

    ``payload_without_signature`` is the acknowledgment body as a ``dict``. The
    ``operator_signature`` key is removed defensively even if present, so the
    same call site can pass the full body or a pre-stripped one and get the
    same hash. See the module docstring for the exact construction a client
    must mirror.
    """
    body = {
        k: _normalize(v) for k, v in payload_without_signature.items() if k != "operator_signature"
    }
    serialized = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


__all__ = ["compute_access_body_hash"]
