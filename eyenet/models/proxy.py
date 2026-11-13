"""ProxyPoolTable + ProxyTable.

Operator-managed rotational proxy pool. One `proxy_pool` is a named bag of
`proxy` rows; identities attach to a pool via `identity.proxy_pool_id` and
the collector claims an ACTIVE proxy at identity-claim time. Sticky vs
non-sticky is a per-identity decision (`identity.proxy_sticky`); sticky
leases set `proxy.bound_identity_id` to the claimant so the next claim by
the same identity reuses the same wire IP (TG requires this for session
stability).

Credential half (SOCKS5 user:pass, HTTP basic, MTProxy hex secret) is
Fernet-encrypted in `secret_encrypted`, same key seam as the identity
session blobs (`<data_dir>/jwt/session_fernet.key`). Host + port stay
plaintext for display + de-dup.

No ``source_id`` FK and no ``identity_id`` FK beyond the sticky-lease
pointer: a pool belongs to the operator, not to a source or identity, so a
TELEGRAM identity and a FORUM identity can both draw from "my cheap
residential SOCKS5" pool if the operator wants.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import ProxyKind, ProxyState

from ._base import new_uuid7


class ProxyPoolTable(SQLModel, table=True):
    __tablename__ = "proxy_pool"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    name: str = Field(unique=True, index=True, max_length=128)
    # Advisory only, not a filter: the operator can label a pool "socks5"
    # even if they later toss an HTTP proxy in. Kept to help the operator
    # remember what the pool is for. ``mixed`` is a valid value.
    kind_hint: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=1024)
    created_at: datetime
    created_by_user_id: UUID | None = Field(default=None, foreign_key="system_user.id")


class ProxyTable(SQLModel, table=True):
    __tablename__ = "proxy"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    pool_id: UUID = Field(foreign_key="proxy_pool.id", index=True)
    kind: ProxyKind = Field(index=True)
    # Host + port kept plaintext: the operator sees them in listings, we
    # de-dup against them, and they are not sensitive on their own (a
    # residential provider's rotating gateway hostname is public).
    host: str = Field(max_length=255)
    port: int
    # Fernet-encrypted at rest. Payload shape varies by kind:
    #   SOCKS5 / HTTP / HTTPS : b"<user>:<pass>" (empty bytes = no auth)
    #   MTPROXY               : the TG hex secret bytes
    # NULL = no credential (anonymous proxy).
    secret_encrypted: bytes | None = None
    state: ProxyState = Field(default=ProxyState.ACTIVE, index=True)
    last_used_at: datetime | None = None
    last_health_check_at: datetime | None = None
    last_error: str | None = Field(default=None, max_length=512)
    # Operator tag (e.g. "stormycloud", "iproxy-20261112", "paste"). Not
    # structured; we grep on it in listings.
    source: str | None = Field(default=None, max_length=128)
    # Set when a sticky lease is in effect: the collector pinned THIS proxy
    # to THIS identity until the identity is retired or the proxy is burned.
    # NULL = available to be leased (ACTIVE) or not applicable.
    bound_identity_id: UUID | None = Field(default=None, foreign_key="identity.id")
    notes: str | None = Field(default=None, max_length=1024)
    created_at: datetime


__all__ = ["ProxyPoolTable", "ProxyTable"]
