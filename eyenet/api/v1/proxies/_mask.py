# SPDX-License-Identifier: AGPL-3.0-or-later
"""Row -> wire response mapping for the proxy routers.

:func:`to_proxy_response` always strips the credential ciphertext so no
caller accidentally echoes it in a log or error payload. :func:`decrypt`
is the operator-admin-only path that peels the Fernet layer when a reveal
is explicitly requested; it is the ONLY place in the API that returns the
plaintext, and the caller is expected to audit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eyenet.contracts.proxy import ProxyAdminResponse, ProxyResponse, ProxyRow

if TYPE_CHECKING:
    from cryptography.fernet import Fernet


def to_proxy_response(row: ProxyRow) -> ProxyResponse:
    """Row -> safe response. Secret is reduced to ``has_secret``."""
    return ProxyResponse(
        id=row.id,
        pool_id=row.pool_id,
        kind=row.kind,
        host=row.host,
        port=row.port,
        has_secret=row.secret_encrypted is not None,
        state=row.state,
        last_used_at=row.last_used_at,
        last_health_check_at=row.last_health_check_at,
        last_error=row.last_error,
        source=row.source,
        bound_identity_id=row.bound_identity_id,
        notes=row.notes,
        created_at=row.created_at,
    )


def to_proxy_admin_response(row: ProxyRow, key: Fernet) -> ProxyAdminResponse:
    """Row -> admin response WITH the decrypted secret. :scope:`proxy:admin` only.

    If the stored ciphertext is somehow malformed (key rotation gone wrong,
    legacy row), return ``secret=None`` rather than crashing the handler;
    the operator sees "credential unreadable" and knows to re-enter.
    """
    secret: str | None = None
    if row.secret_encrypted is not None:
        try:
            secret = key.decrypt(row.secret_encrypted).decode("utf-8")
        except Exception:  # noqa: BLE001 - audit this in the handler, not here
            secret = None
    base = to_proxy_response(row)
    return ProxyAdminResponse(**base.model_dump(), secret=secret)
