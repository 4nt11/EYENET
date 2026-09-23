# SPDX-License-Identifier: AGPL-3.0-or-later
"""`Anchor` — external-witness anchor record (API_PLAN §5.9).

A periodic, server-signed `(audit_head, journal_head)` heartbeat. Each record
binds the deployment's audit-chain head and file-access-journal head at a point
in time under an Ed25519 signature, so an external party can later confirm the
deployment's tamper-evident state as of that moment (and detect a rolled-back
or forked chain). The same records are dispatched on `eyenet.audit.anchor` and
read back via `GET /v1/audit/anchors`.

Surface: db.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from ._base import DbRowBase

_HEX_64 = r"^[0-9a-f]{64}$"


class AnchorRow(DbRowBase):
    """Persisted anchor record. `id` is the row PK; identity is
    `(deployment_id, anchor_seq)`."""

    deployment_id: UUID
    anchor_seq: int = Field(ge=0, description="Monotonic per-deployment counter.")
    anchored_at: datetime
    audit_head: str = Field(pattern=_HEX_64)
    journal_head: str = Field(pattern=_HEX_64)
    signature: str = Field(description="`ed25519:<urlsafe-b64>` over the canonical form.")


__all__ = ["AnchorRow"]
