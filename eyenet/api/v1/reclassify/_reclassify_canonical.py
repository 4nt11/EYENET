# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic canonical form the operator signs for a reclassification (§4.9 -> §5.7).

§4.9 requires an Ed25519 ``operator_signature`` on every reclassify: a session
JWT alone never authorises promoting evidence sensitivity. The signature binds
the operator's INTENT to this exact request. This module pins the EXACT bytes so
the server (verify) and any client (sign) agree.

Canonical construction (DOCUMENTED CONTRACT - a client MUST match):

1. ``body_hash = compute_access_body_hash(request_body)`` - the §5.6 helper,
   reused verbatim. It removes ``operator_signature`` and hashes the sorted-key
   compact JSON of the remaining fields (``new_tier``, ``reason``,
   ``viewing_context``, ``case_refs``). Tamper with any of those and the hash,
   and therefore the signature, no longer verifies.
2. ``canonical = build_canonical(method="POST", url=<request path>,
   request_id="", timestamp="", body_hash=body_hash, content_hash=<hash>)`` -
   the §5.7 length-prefixed injective framing. ``content_hash`` is the subject's
   content sha256 (hex) for an attachment or document, and ``""`` for an
   observation (no content blob). ``request_id`` and ``timestamp`` are empty
   frames: unlike the file-access flow, reclassify does NOT enforce freshness or
   single-use, because a replay of a monotone promote is harmless (it can only
   re-assert the same-or-higher tier, which the CHECK constraint already bounds).

The URL binds the subject id (it is in the path), ``content_hash`` additionally
binds an attachment/document to its exact bytes, and ``body_hash`` binds the
promotion itself. A captured signature therefore cannot be replayed onto a
different row, a different tier, or a different reason.
"""

from __future__ import annotations

from typing import Any

from eyenet.api.v1.attachments._access_canonical import compute_access_body_hash
from eyenet.crypto import build_canonical


def compute_reclassify_body_hash(request_body: dict[str, Any]) -> str:
    """Hex SHA-256 of the reclassify request body, ``operator_signature`` excluded."""
    return compute_access_body_hash(request_body)


def build_reclassify_canonical(*, url: str, body_hash: str, content_hash: str) -> bytes:
    """The §5.7 canonical bytes the operator signs for a reclassification.

    ``content_hash`` is the subject content sha256 (hex) for attachment/document,
    ``""`` for observation. See the module docstring for the full contract.
    """
    return build_canonical(
        "POST",
        url,
        "",
        "",
        body_hash,
        content_hash,
    )


__all__ = ["build_reclassify_canonical", "compute_reclassify_body_hash"]
