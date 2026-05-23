"""`IdentityPool` ABC + `device_fingerprint` (PLAN §6.1).

Two collector implementations MUST produce identical device fingerprint
hashes for identical identities or OPSEC correlation breaks silently. The
per-source input tuples are PINNED here; adding a new source kind requires
updating `_DEVICE_FINGERPRINT_SCHEMAS` and a contract test.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any

from .enums import IdentityState, SourceKind

# Per-source canonical input tuple. The order of keys matters for the hash —
# we sort keys at hash time so that callers can pass kwargs in any order.
_DEVICE_FINGERPRINT_SCHEMAS: dict[SourceKind, frozenset[str]] = {
    SourceKind.TELEGRAM: frozenset(
        {"api_id", "device_model", "system_version", "app_version", "lang_code", "system_lang_code"}
    ),
    SourceKind.MATRIX: frozenset({"homeserver_url", "device_id", "user_agent"}),
    SourceKind.IRC: frozenset({"server", "nick", "ident", "realname", "client_version"}),
    SourceKind.DISCORD: frozenset({"client_build_number", "user_agent", "super_properties_hash"}),
    SourceKind.FORUM: frozenset({"user_agent", "accept_language", "tls_fingerprint"}),
}


def device_fingerprint(source_kind: SourceKind | str, /, **inputs: Any) -> str:
    """Compute the per-identity device fingerprint hash.

    `device_fingerprint = sha256(canonical_json(inputs))`. PLAN §6.1.

    Raises ValueError if the source kind is unknown or required fields are
    missing — silent fingerprint divergence is the failure mode this
    function exists to prevent.
    """

    kind = SourceKind(source_kind) if not isinstance(source_kind, SourceKind) else source_kind
    schema = _DEVICE_FINGERPRINT_SCHEMAS.get(kind)
    if schema is None:
        raise ValueError(
            f"unknown source kind {kind!r}; register its tuple shape in "
            "contracts/identity_pool.py:_DEVICE_FINGERPRINT_SCHEMAS first"
        )
    provided = frozenset(inputs.keys())
    if provided != schema:
        missing = schema - provided
        extra = provided - schema
        raise ValueError(
            f"device_fingerprint inputs for {kind!r} mismatch: "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )
    canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class IdentityPool(ABC):
    """Abstract operator-identity pool.

    A collector instance `claim`s an identity for the duration of its run.
    Rotation mid-session is itself a fingerprint — so it isn't allowed.
    """

    @abstractmethod
    async def claim(self, name: str) -> object:
        """Atomically claim identity `name` and mark it `in_use`. Returns the
        IdentityRow (object-typed to keep this layer free of import cycles)."""

    @abstractmethod
    async def release(self, name: str, *, new_state: IdentityState) -> None:
        """Release a claim, transitioning to `cooling`/`available`/`frozen`/`burned`."""

    @abstractmethod
    async def freeze_all(self) -> None:
        """Kill-switch path: freeze every identity in the pool (PLAN §6.2)."""


__all__ = ["IdentityPool", "device_fingerprint"]
