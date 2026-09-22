# SPDX-License-Identifier: AGPL-3.0-or-later
"""Server-side Ed25519 signer for file-access exoneration records (API_PLAN §5.8).

An exoneration is a SERVER-signed answer to "who accessed this content, and was
that everything?" (by-hash) or "what did this operator access?" (by-user). The
server holds a single long-lived Ed25519 keypair at rest; every exoneration
response carries a detached signature over an injection-proof canonical so a
third party (defence counsel, an auditor) can verify the answer was produced by
this deployment and was not altered in transit. An EMPTY access list is a
POSITIVE cryptographic assertion of non-access, so it must be signed too.

Canonical contract (``EYENET-EXONERATION-v1``) — a verifier MUST reconstruct
these exact bytes, in this exact order, all length-prefixed (reusing the
``_frame`` framing so no field can run into the next):

1. framed scheme tag ``EYENET-EXONERATION-v1``
2. ``query_kind``            : ``"by_hash"`` or ``"by_user"``
3. ``content_hash``          : 32 raw bytes for by-hash; EMPTY (b"") for by-user
4. ``user_id``               : 16 raw bytes for by-user; EMPTY for by-hash
5. ``since``                 : ISO-8601 or "" (by-user window lower bound)
6. ``until``                 : ISO-8601 or "" (by-user window upper bound)
7. ``query_time``            : ISO-8601 of when the answer was produced
8. ``journal_head``          : 32 raw bytes, the journal ``self_hash`` at query
9. ``len(access_ids)``       : decimal string
10. each ``access_id``       : 16 raw bytes, in the RETURNED order

WHY user_id + window are bound (obey this): the on-the-wire
:class:`FileAccessExoneration` envelope has NO user_id / since / until fields, it
carries a sentinel ``content_hash`` for by-user queries. Without binding the
query identity into the SIGNED canonical, two DIFFERENT operators' empty by-user
assertions would produce byte-identical canonicals and therefore identical
signatures: a confusion/forgery vector where operator B replays operator A's
signed "you accessed nothing" as their own. The verifier supplies user_id +
window from THEIR OWN query when reconstructing, so a signature only verifies for
the exact query it was minted for. by-hash binds the content_hash for the same
reason.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ._file_access_signing import _frame, _frame_bytes, fingerprint

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_EXON_SCHEME: Final[bytes] = b"EYENET-EXONERATION-v1"
_SIG_PREFIX: Final[str] = "ed25519:"
_KEY_NAME: Final[str] = "exoneration_ed25519.key"

# Sentinel content_hash carried in the FileAccessExoneration envelope for a
# by-user query (the envelope has no user field). It is NOT what the canonical
# binds — the canonical binds the real user_id + window — it is only the wire
# placeholder for the required hex64 field.
BY_USER_CONTENT_HASH_SENTINEL: Final[str] = "0" * 64


def build_exoneration_canonical(
    *,
    query_kind: str,
    content_hash: bytes,
    user_id: bytes,
    since: str,
    until: str,
    query_time: str,
    journal_head: bytes,
    access_ids: Sequence[bytes],
) -> bytes:
    """Build the injection-proof ``EYENET-EXONERATION-v1`` signing bytes.

    See the module docstring for the field order + the user-binding rationale.
    ``query_kind`` is ``"by_hash"`` or ``"by_user"``; the unused identity fields
    are passed EMPTY (``b""`` / ``""``) and still framed, so the two query kinds
    can never collide.
    """
    return _frame_bytes(_EXON_SCHEME) + b"".join(
        (
            _frame(query_kind),
            _frame_bytes(content_hash),
            _frame_bytes(user_id),
            _frame(since),
            _frame(until),
            _frame(query_time),
            _frame_bytes(journal_head),
            _frame(str(len(access_ids))),
            *(_frame_bytes(a) for a in access_ids),
        )
    )


@dataclass(frozen=True, slots=True)
class ExonerationSigner:
    """Holds the server exoneration private key and signs canonicals."""

    _private_key: Ed25519PrivateKey

    def sign(self, canonical: bytes) -> str:
        """Sign ``canonical`` and return the ``ed25519:<urlsafe-b64>`` wire form."""
        sig = self._private_key.sign(canonical)
        return _SIG_PREFIX + base64.urlsafe_b64encode(sig).decode("ascii")

    @property
    def verifying_key_bytes(self) -> bytes:
        """Raw 32-byte Ed25519 public key (for verifiers/tests)."""
        from cryptography.hazmat.primitives import serialization  # noqa: PLC0415

        return self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    @property
    def fingerprint(self) -> str:
        """16-hex fingerprint of the server verifying key."""
        return fingerprint(self._private_key.public_key())


def load_exoneration_key(data_dir: Path) -> ExonerationSigner:
    """Return the server :class:`ExonerationSigner`, materializing the key once.

    Stored at ``<data_dir>/jwt/exoneration_ed25519.key`` (raw 32 private-key
    bytes, mode 0600), alongside the JWT keypair / MFA key / PAT pepper: same
    boot path, same operator backup story. Losing this file invalidates every
    previously-issued exoneration signature (verifiers can no longer confirm
    them); the deployment simply re-signs on the next query with the new key.
    """
    jwt_dir = data_dir / "jwt"
    jwt_dir.mkdir(parents=True, exist_ok=True)
    key_path = jwt_dir / _KEY_NAME
    if not key_path.exists():
        private_key = Ed25519PrivateKey.generate()
        raw = private_key.private_bytes_raw()
        key_path.write_bytes(raw)
        key_path.chmod(0o600)
    return ExonerationSigner(Ed25519PrivateKey.from_private_bytes(key_path.read_bytes()))


__all__ = [
    "BY_USER_CONTENT_HASH_SENTINEL",
    "ExonerationSigner",
    "build_exoneration_canonical",
    "load_exoneration_key",
]
