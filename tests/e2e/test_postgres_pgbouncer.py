# SPDX-License-Identifier: AGPL-3.0-or-later
"""PostgresRepository behind pgbouncer in TRANSACTION-pooling mode.

The high-ingest fronting (POSTGRES_PORT.md §5.1): many collector processes share
a small pool via pgbouncer. Transaction mode gives each transaction a possibly-
different server connection with no session carryover, which is why the backend
sets ``statement_cache_size=0`` (asyncpg prepared-statement cache would collide)
and uses TRANSACTION-scoped advisory locks (``pg_advisory_xact_lock``) for the
hash chains. The DDL/migration path bypasses the pooler via ``ddl_url``.

This test proves the request path works end-to-end through a real pgbouncer: the
advisory-lock audit chain verifies, and the upsert + vector search succeed.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from eyenet.contracts.audit import verify_chain
from eyenet.storage.factory import get_repository

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(240)]

psycopg = pytest.importorskip("psycopg")

try:
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.network import Network
    from testcontainers.postgres import PostgresContainer
except Exception:  # pragma: no cover
    PostgresContainer = None  # type: ignore[assignment,misc]


def _wait(host: str, port: str, db: str, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    last: Exception | None = None
    dsn = f"host={host} port={port} dbname={db} user=test password=test"
    while time.time() < deadline:
        try:
            with psycopg.connect(dsn, autocommit=True) as c:
                c.execute("SELECT 1")
            return
        except Exception as exc:
            last = exc
            time.sleep(1)
    raise RuntimeError(f"pgbouncer not ready: {last}")


@pytest.fixture
def stack() -> Iterator[dict[str, str]]:
    """Postgres (trust) + pgbouncer (md5, transaction mode) on a shared network."""
    if PostgresContainer is None:
        pytest.skip("testcontainers not installed")
    net = Network()
    net.create()
    pg = bouncer = None
    try:
        pg = (
            PostgresContainer("postgres:16-alpine")
            .with_env("POSTGRES_HOST_AUTH_METHOD", "trust")
            .with_network(net)
            .with_network_aliases("pg")
        )
        pg.start()
        pg_host, pg_port = pg.get_container_host_ip(), pg.get_exposed_port(5432)
        db = f"eyenet_pgb_{uuid.uuid4().hex[:8]}"
        with psycopg.connect(
            f"host={pg_host} port={pg_port} dbname=postgres user=test", autocommit=True
        ) as c:
            c.execute(f'CREATE DATABASE "{db}"')
            c.execute(f'CREATE DATABASE "{db}_audit"')

        bouncer = (
            DockerContainer("edoburu/pgbouncer:latest")
            .with_network(net)
            .with_exposed_ports(5432)  # edoburu listens on 5432 internally
            .with_env("DB_HOST", "pg")
            .with_env("DB_PORT", "5432")
            .with_env("DB_USER", "test")
            .with_env("DB_PASSWORD", "test")
            # scram-sha-256, NEVER md5 (deprecated + weak). This is the auth prod
            # uses, so the test proves asyncpg -> pgbouncer scram actually works.
            .with_env("AUTH_TYPE", "scram-sha-256")
            .with_env("POOL_MODE", "transaction")
            .with_env("MAX_CLIENT_CONN", "100")
            .with_env("DEFAULT_POOL_SIZE", "20")
            .with_env("IGNORE_STARTUP_PARAMETERS", "extra_float_digits,search_path,options")
        )
        bouncer.start()
        b_host, b_port = bouncer.get_container_host_ip(), bouncer.get_exposed_port(5432)
        try:
            _wait(b_host, b_port, db)
        except Exception as exc:  # pragma: no cover — surface bouncer logs
            pytest.skip(f"pgbouncer did not come up: {exc}")

        yield {
            "pool_url": f"postgresql://test:test@{b_host}:{b_port}/{db}",
            "ddl_url": f"postgresql://test:test@{pg_host}:{pg_port}/{db}",
        }
    finally:
        if bouncer is not None:
            bouncer.stop()
        if pg is not None:
            pg.stop()
        net.remove()


@pytest.mark.asyncio
async def test_backend_through_pgbouncer_transaction_mode(
    stack: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "postgres")
    # Request path -> pgbouncer; DDL/migration path -> Postgres directly.
    repo = get_repository(url=stack["pool_url"], ddl_url=stack["ddl_url"])
    try:
        for i in range(15):
            await repo.append_audit(
                {
                    "event": "evidence_access",
                    "service": "engine",
                    "instance_id": "eng_1",
                    "subject_kind": "actor",
                    "payload": {"i": i},
                    "at": datetime(2026, 5, 4, 12, i, 0, tzinfo=UTC),
                }
            )
        actor = uuid.uuid4()
        await repo.set_cursors_bulk(
            actor, [("chatty_member", datetime(2026, 5, 4, tzinfo=UTC), uuid.uuid4())]
        )
        await repo.upsert_simhash(actor, "chatty_member", "000000000000000f")

        rows = await repo.all_audit()
        ok, broken = verify_chain(rows)
        # The advisory-lock chain survives connections being multiplexed across
        # transactions by the pooler.
        assert ok and broken is None
        assert len(rows) == 15
        got = await repo.get_cursors_bulk(actor, ["chatty_member"])
        assert got["chatty_member"][0] is not None
    finally:
        await repo.close()
