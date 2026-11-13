"""Proxy pool contracts (v1.2.0).

Rows:
- :class:`ProxyPoolRow`: a named bag of proxies.
- :class:`ProxyRow`: one proxy entry. ``secret`` is never serialized on
  :scope:`proxy:read` responses; only :scope:`proxy:admin` reads it back
  decrypted, and even then the API layer is responsible for masking it on
  the wire unless the caller asks for the raw.

Requests:
- :class:`ProxyPoolCreateRequest` / :class:`ProxyPoolUpdateRequest`: pool CRUD.
- :class:`ProxyCreateRequest`: one proxy. The raw ``secret`` on the wire is
  Fernet-encrypted by the API handler before touching the DB; it never lives
  decrypted at rest.
- :class:`ProxyBulkCreateRequest`: paste a textarea of lines in common proxy
  URI formats (``socks5://user:pass@host:port``, ``host:port:user:pass``,
  ``host:port``, ``mtproto://host:port?secret=HEX``). The handler parses
  each line, rejects malformed entries loudly, and inserts the rest.
- :class:`ProxyStateUpdateRequest`: operator mark-burned / mark-active.
- :class:`IdentityProxyBindRequest`: attach/detach a pool to an identity +
  flip sticky.

Everything here is a pydantic ``BaseModel``; the row types extend
``DbRowBase`` so storage can return them directly. Surface: db + request.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ._base import DbRowBase
from .enums import ProxyKind, ProxyState


class ProxyPoolRow(DbRowBase):
    """Persisted proxy_pool row."""

    name: str
    kind_hint: str | None = None
    description: str | None = None
    created_at: datetime
    created_by_user_id: UUID | None = None


class ProxyRow(DbRowBase):
    """Persisted proxy row. ``secret_encrypted`` is the raw ciphertext.

    API callers never see this type directly: the handler maps it to a
    :class:`ProxyResponse` (secret always masked) or :class:`ProxyAdminResponse`
    (secret decrypted, :scope:`proxy:admin` only).
    """

    pool_id: UUID
    kind: ProxyKind
    host: str
    port: int
    secret_encrypted: bytes | None = None
    state: ProxyState
    last_used_at: datetime | None = None
    last_health_check_at: datetime | None = None
    last_error: str | None = None
    source: str | None = None
    bound_identity_id: UUID | None = None
    notes: str | None = None
    created_at: datetime


# ---------- API requests ------------------------------------------------


class ProxyPoolCreateRequest(BaseModel):
    """POST /v1/proxy-pools. :scope:`proxy:admin`."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=128)
    kind_hint: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=1024)


class ProxyPoolUpdateRequest(BaseModel):
    """PATCH /v1/proxy-pools/{id}. :scope:`proxy:admin`.

    All fields optional; only non-None values are applied.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=128)
    kind_hint: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=1024)


class ProxyCreateRequest(BaseModel):
    """POST /v1/proxy-pools/{id}/proxies. :scope:`proxy:write`.

    ``secret`` is the plaintext credential on the wire; the handler
    Fernet-encrypts it before storage. For MTPROXY, ``secret`` is the hex
    secret string.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    kind: ProxyKind
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    secret: str | None = Field(default=None, max_length=512)
    source: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=1024)


class ProxyBulkCreateRequest(BaseModel):
    """POST /v1/proxy-pools/{id}/proxies/bulk. :scope:`proxy:admin`.

    One proxy per line in ``lines``. Accepted shapes per line (whitespace
    trimmed, blank + ``#`` comment lines ignored):

    - ``socks5://host:port``                                 (anon SOCKS5)
    - ``socks5://user:pass@host:port``                       (auth SOCKS5)
    - ``http://host:port`` / ``https://...`` / ``http(s)://user:pass@...``
    - ``mtproto://host:port?secret=HEX``                     (TG MTProxy)
    - ``host:port``                                          (defaults ``kind`` to the pool's ``kind_hint``, else SOCKS5)
    - ``host:port:user:pass``                                (same default kind)

    The handler parses each line, reports malformed ones in the response,
    and inserts the rest.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    lines: list[str] = Field(min_length=1, max_length=10_000)
    default_kind: ProxyKind | None = None
    source: str | None = Field(default=None, max_length=128)


class ProxyStateUpdateRequest(BaseModel):
    """POST /v1/proxies/{id}/state. :scope:`proxy:write`."""

    state: ProxyState
    reason: str | None = Field(default=None, max_length=512)


class IdentityProxyBindRequest(BaseModel):
    """PATCH /v1/identities/{id}/proxy. :scope:`proxy:write` + :scope:`write:identity`.

    Pass ``pool_id=None`` to detach. ``sticky=None`` means "use the source-kind
    default" (TG/matrix sticky, forum non-sticky).
    """

    pool_id: UUID | None = None
    sticky: bool | None = None


# ---------- API responses ----------------------------------------------


class ProxyResponse(BaseModel):
    """GET /v1/proxy-pools/{id}/proxies/{proxy_id}. :scope:`proxy:read`.

    Secret NEVER included at this level, even masked. ``has_secret`` lets the
    UI render "credential set / none" without leaking length.
    """

    id: UUID
    pool_id: UUID
    kind: ProxyKind
    host: str
    port: int
    has_secret: bool
    state: ProxyState
    last_used_at: datetime | None
    last_health_check_at: datetime | None
    last_error: str | None
    source: str | None
    bound_identity_id: UUID | None
    notes: str | None
    created_at: datetime


class ProxyAdminResponse(ProxyResponse):
    """GET /v1/proxies/{id}?reveal=true. :scope:`proxy:admin`.

    Adds the decrypted ``secret`` for operator-triggered credential recovery
    (lost password manager, debugging). Auditable via the standard
    audit_log; the handler writes a ``PROXY_SECRET_REVEALED`` event.
    """

    secret: str | None


class ProxyBulkCreateResult(BaseModel):
    """Result of a bulk import (:class:`ProxyBulkCreateRequest`)."""

    inserted: int
    skipped_duplicate: int
    rejected: list[str]  # one message per rejected line: "line 3: unparseable: ..."


__all__ = [
    "IdentityProxyBindRequest",
    "ProxyAdminResponse",
    "ProxyBulkCreateRequest",
    "ProxyBulkCreateResult",
    "ProxyCreateRequest",
    "ProxyPoolCreateRequest",
    "ProxyPoolRow",
    "ProxyPoolUpdateRequest",
    "ProxyResponse",
    "ProxyRow",
    "ProxyStateUpdateRequest",
]
