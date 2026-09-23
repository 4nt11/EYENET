# SPDX-License-Identifier: AGPL-3.0-or-later
"""Server-side Ed25519 signing for external-witness anchors (API_PLAN §5.9).

An anchor is a SERVER-signed `(audit_head, journal_head)` heartbeat: proof that,
at `anchored_at`, this deployment's audit chain and file-access journal had these
exact heads. A third party can later confirm the deployment has not rolled back
or forked either chain. The signer reuses the same generic Ed25519 wrapper as
the exoneration path (:class:`ExonerationSigner`); only the key file and the
canonical scheme differ.

Canonical contract (``EYENET-ANCHOR-v1``) — length-prefixed via ``_frame`` so
no field runs into the next; a verifier reconstructs these exact bytes:

1. framed scheme tag ``EYENET-ANCHOR-v1``
2. ``deployment_id``  : 16 raw bytes
3. ``anchor_seq``     : decimal string
4. ``anchored_at``    : ISO-8601
5. ``audit_head``     : hex64 string
6. ``journal_head``   : hex64 string
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ._exoneration_signing import ExonerationSigner
from ._file_access_signing import _frame, _frame_bytes

if TYPE_CHECKING:
    from pathlib import Path
    from uuid import UUID

_ANCHOR_SCHEME: Final[bytes] = b"EYENET-ANCHOR-v1"
_KEY_NAME: Final[str] = "anchor_ed25519.key"
_DEPLOYMENT_ID_NAME: Final[str] = "deployment_id"


def build_anchor_canonical(
    *,
    deployment_id: UUID,
    anchor_seq: int,
    anchored_at: str,
    audit_head: str,
    journal_head: str,
) -> bytes:
    """Build the injection-proof ``EYENET-ANCHOR-v1`` signing bytes."""
    return _frame_bytes(_ANCHOR_SCHEME) + b"".join(
        (
            _frame_bytes(deployment_id.bytes),
            _frame(str(anchor_seq)),
            _frame(anchored_at),
            _frame(audit_head),
            _frame(journal_head),
        )
    )


def load_anchor_key(data_dir: Path) -> ExonerationSigner:
    """Return the deployment anchor signer, materializing the key once.

    Stored at ``<data_dir>/jwt/anchor_ed25519.key`` (raw 32 private-key bytes,
    mode 0600) alongside the other server keys. ``ExonerationSigner`` is reused
    verbatim as the generic Ed25519 signer (its ``sign`` emits the
    ``ed25519:<urlsafe-b64>`` wire form).
    """
    jwt_dir = data_dir / "jwt"
    jwt_dir.mkdir(parents=True, exist_ok=True)
    key_path = jwt_dir / _KEY_NAME
    if not key_path.exists():
        private_key = Ed25519PrivateKey.generate()
        key_path.write_bytes(private_key.private_bytes_raw())
        key_path.chmod(0o600)
    return ExonerationSigner(Ed25519PrivateKey.from_private_bytes(key_path.read_bytes()))


def load_or_create_deployment_id(data_dir: Path) -> UUID:
    """Return this deployment's stable UUID, materializing it once.

    No per-deployment identity exists elsewhere; we mint one on first use and
    persist it at ``<data_dir>/deployment_id`` so the emitter and any reader
    agree. Deleting it starts a fresh anchor lineage.
    """
    path = data_dir / _DEPLOYMENT_ID_NAME
    if not path.exists():
        path.write_text(str(uuid.uuid4()), encoding="ascii")
    return uuid.UUID(path.read_text(encoding="ascii").strip())


__all__ = [
    "build_anchor_canonical",
    "load_anchor_key",
    "load_or_create_deployment_id",
]
