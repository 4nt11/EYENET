# SPDX-License-Identifier: AGPL-3.0-or-later
"""ProxiesMixin - proxy_pool + proxy CRUD + identity binding (v1.2.0).

ANSI SQL only (CLAUDE.md §2.3 Rule 1). No ``ON CONFLICT``, no triggers.
The (host, port, kind) uniqueness on ``proxy`` is a DB-level constraint,
so duplicate inserts raise :class:`IntegrityError`; the bulk helper
pre-checks in-session and skips rather than rolling back the whole batch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from eyenet.contracts.enums import ProxyKind, ProxyState, SourceKind
from eyenet.contracts.identity import IdentityRow
from eyenet.contracts.proxy import ProxyPoolRow, ProxyRow
from eyenet.models.identity import IdentityTable
from eyenet.models.proxy import ProxyPoolTable, ProxyTable

from ._helpers import safe_session


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _pool_row(t: ProxyPoolTable) -> ProxyPoolRow:
    data = t.model_dump()
    data["created_at"] = _coerce_utc(data.get("created_at"))
    return ProxyPoolRow.model_validate(data)


def _proxy_row(t: ProxyTable) -> ProxyRow:
    data = t.model_dump()
    for k in ("created_at", "last_used_at", "last_health_check_at"):
        data[k] = _coerce_utc(data.get(k))
    return ProxyRow.model_validate(data)


def _identity_row(t: IdentityTable) -> IdentityRow:
    data = t.model_dump()
    for k in ("last_used_at", "graduated_at"):
        data[k] = _coerce_utc(data.get(k))
    return IdentityRow.model_validate(data)


# Convenience: which SourceKind defaults to sticky when identity.proxy_sticky is NULL.
_STICKY_BY_SOURCE_KIND: dict[SourceKind, bool] = {
    SourceKind.TELEGRAM: True,  # auth_key + IP consistency; must not rotate
    SourceKind.MATRIX: True,     # session + device fingerprint
    SourceKind.FORUM: False,     # per-request rotation is fine
    SourceKind.DISCORD: True,    # tokens are IP-bound
    SourceKind.OPERATOR: False,  # not a wire source
}


class ProxiesMixin:
    """CRUD + lease surface for proxy pools and proxies."""

    # ----- proxy_pool CRUD -------------------------------------------

    async def create_proxy_pool(
        self,
        *,
        name: str,
        kind_hint: str | None,
        description: str | None,
        created_at: datetime,
        created_by_user_id: UUID | None,
    ) -> ProxyPoolRow:
        table = ProxyPoolTable(
            name=name,
            kind_hint=kind_hint,
            description=description,
            created_at=created_at,
            created_by_user_id=created_by_user_id,
        )
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            session.add(table)
            await session.commit()
            await session.refresh(table)
        return _pool_row(table)

    async def get_proxy_pool(self, pool_id: UUID) -> ProxyPoolRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(ProxyPoolTable).where(ProxyPoolTable.id == pool_id))
            row = result.first()
        return _pool_row(row) if row else None

    async def get_proxy_pool_by_name(self, name: str) -> ProxyPoolRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(ProxyPoolTable).where(ProxyPoolTable.name == name))
            row = result.first()
        return _pool_row(row) if row else None

    async def list_proxy_pools(self) -> list[ProxyPoolRow]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(ProxyPoolTable).order_by(col(ProxyPoolTable.name))
            )
            return [_pool_row(r) for r in result.all()]

    async def update_proxy_pool(
        self,
        pool_id: UUID,
        *,
        name: str | None = None,
        kind_hint: str | None = None,
        description: str | None = None,
    ) -> ProxyPoolRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(ProxyPoolTable).where(ProxyPoolTable.id == pool_id))
            row = result.first()
            if row is None:
                return None
            if name is not None:
                row.name = name
            if kind_hint is not None:
                row.kind_hint = kind_hint
            if description is not None:
                row.description = description
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _pool_row(row)

    async def delete_proxy_pool(self, pool_id: UUID) -> bool:
        """Delete a pool. Raises :class:`ValueError` if the pool still has proxies.

        No cascade: deleting a pool with members would strand identities that
        still reference it + silently invalidate audit evidence. Operator
        removes members first.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            count_result = await session.exec(
                select(ProxyTable.id).where(ProxyTable.pool_id == pool_id)
            )
            if count_result.first() is not None:
                raise ValueError("proxy_pool is not empty; remove all proxies first")
            result = await session.exec(select(ProxyPoolTable).where(ProxyPoolTable.id == pool_id))
            row = result.first()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
        return True

    # ----- proxy CRUD -------------------------------------------------

    async def create_proxy(
        self,
        *,
        pool_id: UUID,
        kind: ProxyKind,
        host: str,
        port: int,
        secret_encrypted: bytes | None,
        source: str | None,
        notes: str | None,
        created_at: datetime,
    ) -> ProxyRow:
        table = ProxyTable(
            pool_id=pool_id,
            kind=kind,
            host=host,
            port=port,
            secret_encrypted=secret_encrypted,
            source=source,
            notes=notes,
            created_at=created_at,
        )
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            session.add(table)
            await session.commit()
            await session.refresh(table)
        return _proxy_row(table)

    async def get_proxy(self, proxy_id: UUID) -> ProxyRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(ProxyTable).where(ProxyTable.id == proxy_id))
            row = result.first()
        return _proxy_row(row) if row else None

    async def list_proxies(
        self,
        *,
        pool_id: UUID | None = None,
        state: ProxyState | None = None,
    ) -> list[ProxyRow]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(ProxyTable)
            if pool_id is not None:
                stmt = stmt.where(ProxyTable.pool_id == pool_id)
            if state is not None:
                stmt = stmt.where(ProxyTable.state == state)
            stmt = stmt.order_by(col(ProxyTable.created_at).desc())
            result = await session.exec(stmt)
            return [_proxy_row(r) for r in result.all()]

    async def update_proxy_state(
        self,
        proxy_id: UUID,
        *,
        state: ProxyState,
        last_error: str | None = None,
    ) -> ProxyRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(ProxyTable).where(ProxyTable.id == proxy_id))
            row = result.first()
            if row is None:
                return None
            row.state = state
            if last_error is not None:
                row.last_error = last_error
            if state in (ProxyState.BURNED, ProxyState.DISABLED):
                # Release any sticky binding so the next claim can pick a fresh one.
                row.bound_identity_id = None
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _proxy_row(row)

    async def delete_proxy(self, proxy_id: UUID) -> bool:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(ProxyTable).where(ProxyTable.id == proxy_id))
            row = result.first()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
        return True

    async def bulk_create_proxies(
        self,
        *,
        pool_id: UUID,
        entries: list[dict[str, object]],
        created_at: datetime,
    ) -> dict[str, object]:
        """Insert many proxies in one session. Returns counts + skipped reasons.

        ``entries`` is a list of dicts shaped like the ``create_proxy`` kwargs
        (``kind``, ``host``, ``port``, ``secret_encrypted``, ``source``,
        ``notes``). Entries that collide on the (host, port, kind) unique
        constraint are skipped (not rolled back); other errors bubble up.
        """
        inserted = 0
        skipped: list[str] = []
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            # Pre-fetch existing (host, port, kind) tuples in the WHOLE DB so
            # we can skip duplicates in-memory without a per-row savepoint.
            existing_stmt = select(ProxyTable.host, ProxyTable.port, ProxyTable.kind)
            existing_result = await session.exec(existing_stmt)
            existing = {(h, p, k) for h, p, k in existing_result.all()}

            for entry in entries:
                key = (entry["host"], entry["port"], entry["kind"])
                if key in existing:
                    skipped.append(f"{entry['host']}:{entry['port']} ({entry['kind']})")
                    continue
                existing.add(key)
                table = ProxyTable(
                    pool_id=pool_id,
                    kind=entry["kind"],
                    host=entry["host"],
                    port=entry["port"],
                    secret_encrypted=entry.get("secret_encrypted"),
                    source=entry.get("source"),
                    notes=entry.get("notes"),
                    created_at=created_at,
                )
                session.add(table)
                inserted += 1
            try:
                await session.commit()
            except IntegrityError as exc:
                # Shouldn't happen given the pre-filter, but belt-and-suspenders.
                await session.rollback()
                raise RuntimeError(f"bulk insert failed: {exc}") from exc
        return {"inserted": inserted, "skipped_duplicate": len(skipped), "skipped_keys": skipped}

    # ----- identity <-> pool binding ---------------------------------

    async def bind_identity_proxy_pool(
        self,
        identity_id: UUID,
        *,
        pool_id: UUID | None,
        sticky: bool | None,
    ) -> IdentityRow | None:
        """Set or clear an identity's proxy pool attachment + sticky flag.

        Passing ``pool_id=None`` detaches. ``sticky=None`` means "fall back to
        the source-kind default" (telegram/matrix sticky, forum non-sticky).
        If detaching, any existing sticky binding on proxies for this
        identity is released so the proxies go back to the lease pool.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(IdentityTable).where(IdentityTable.id == identity_id))
            row = result.first()
            if row is None:
                return None
            row.proxy_pool_id = pool_id
            row.proxy_sticky = sticky
            session.add(row)
            # Release stale sticky bindings when detaching or switching pools.
            bound_result = await session.exec(
                select(ProxyTable).where(ProxyTable.bound_identity_id == identity_id)
            )
            for proxy in bound_result.all():
                if pool_id is None or proxy.pool_id != pool_id:
                    proxy.bound_identity_id = None
                    session.add(proxy)
            await session.commit()
            await session.refresh(row)
        return _identity_row(row)

    # ----- lease flow (used by collectors; wired separately) ---------

    async def lease_proxy_for_identity(
        self,
        identity_id: UUID,
        *,
        source_kind: SourceKind,
    ) -> ProxyRow | None:
        """Lease a proxy for a collector claim. Returns None if the identity
        has no pool attached (collector then uses direct connection).

        Sticky semantics:
        - ``identity.proxy_sticky`` is True (or NULL + source-kind defaults sticky):
          reuse the proxy already bound to this identity if present, else lease
          an ACTIVE one and bind it.
        - Non-sticky: pick the ACTIVE proxy with the oldest ``last_used_at``
          (LRU) and bump its ``last_used_at``, no binding.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            id_result = await session.exec(
                select(IdentityTable).where(IdentityTable.id == identity_id)
            )
            identity = id_result.first()
            if identity is None or identity.proxy_pool_id is None:
                return None

            sticky = identity.proxy_sticky
            if sticky is None:
                sticky = _STICKY_BY_SOURCE_KIND.get(source_kind, True)

            now = datetime.now(tz=UTC).replace(tzinfo=None)

            if sticky:
                # Reuse existing binding if alive.
                bound = await session.exec(
                    select(ProxyTable).where(
                        ProxyTable.bound_identity_id == identity_id,
                        ProxyTable.pool_id == identity.proxy_pool_id,
                        ProxyTable.state == ProxyState.ACTIVE,
                    )
                )
                existing = bound.first()
                if existing is not None:
                    existing.last_used_at = now
                    session.add(existing)
                    await session.commit()
                    await session.refresh(existing)
                    return _proxy_row(existing)
                # Lease a fresh one and bind.
                fresh = await session.exec(
                    select(ProxyTable).where(
                        ProxyTable.pool_id == identity.proxy_pool_id,
                        ProxyTable.state == ProxyState.ACTIVE,
                        col(ProxyTable.bound_identity_id).is_(None),
                    ).order_by(col(ProxyTable.last_used_at).asc().nulls_first())
                )
                row = fresh.first()
                if row is None:
                    return None
                row.bound_identity_id = identity_id
                row.last_used_at = now
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return _proxy_row(row)

            # Non-sticky: LRU over ACTIVE proxies, no binding.
            lru = await session.exec(
                select(ProxyTable).where(
                    ProxyTable.pool_id == identity.proxy_pool_id,
                    ProxyTable.state == ProxyState.ACTIVE,
                ).order_by(col(ProxyTable.last_used_at).asc().nulls_first())
            )
            row = lru.first()
            if row is None:
                return None
            row.last_used_at = now
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _proxy_row(row)


__all__ = ["ProxiesMixin"]
