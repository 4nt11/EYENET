# SPDX-License-Identifier: AGPL-3.0-or-later
"""proxy_pool + proxy tables, identity.proxy_pool_id + identity.proxy_sticky

Revision ID: 0023_proxy_pools
Revises: 0022_stealer_processing
Create Date: 2026-11-12

Operator-managed rotational / sticky proxy pool for collectors. A `proxy_pool`
is a named bag of `proxy` rows the operator curates; identities attach to a
pool and claim an active proxy at identity-claim time. `proxy_sticky` controls
whether that claim binds for the identity's lifetime (Telegram default:
sticky, since TG checks auth_key + IP consistency) or is one-shot per
operation (forum default: free rotation is fine on anonymous crawls).

The proxy credential half (SOCKS5 user:pass, HTTP basic, MTProxy hex secret)
is stored Fernet-encrypted in `proxy.secret_encrypted` using the same
`session_fernet.key` seam as the identity session blobs. Host + port stay
plaintext for display + de-dup. `proxy:admin` is required to read the raw
credential back; `proxy:read` sees only (host, port, kind, state, source).

Main DB only; audit DB is untouched. Fresh deploys build this from model
metadata via `create_all`; this incremental only touches an already-populated
live DB, hence `IF NOT EXISTS` everywhere.
"""

from __future__ import annotations

from alembic import op

revision = "0023_proxy_pools"
down_revision = "0022_stealer_processing"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    # ----- enums -------------------------------------------------------
    # Native PG enums; SQLAlchemy stores the member NAME (uppercase), see
    # reference_pg_native_enum_stores_names_not_values.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE proxykind AS ENUM ('SOCKS5', 'HTTP', 'HTTPS', 'MTPROXY');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE proxystate AS ENUM ('ACTIVE', 'COOLING', 'BURNED', 'DISABLED');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        """
    )

    # ----- proxy_pool --------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS proxy_pool (
            id                    uuid PRIMARY KEY,
            name                  varchar(128) NOT NULL UNIQUE,
            kind_hint             varchar(32),
            description           varchar(1024),
            created_at            timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
            created_by_user_id    uuid REFERENCES system_user (id)
        )
        """
    )

    # ----- proxy -------------------------------------------------------
    # bound_identity_id is set when a sticky lease is in effect. UNIQUE
    # (host, port, kind) prevents the operator accidentally double-adding
    # the same proxy under two entries in the same or different pools.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS proxy (
            id                    uuid PRIMARY KEY,
            pool_id               uuid NOT NULL REFERENCES proxy_pool (id),
            kind                  proxykind NOT NULL,
            host                  varchar(255) NOT NULL,
            port                  integer NOT NULL,
            secret_encrypted      bytea,
            state                 proxystate NOT NULL DEFAULT 'ACTIVE',
            last_used_at          timestamp,
            last_health_check_at  timestamp,
            last_error            varchar(512),
            source                varchar(128),
            bound_identity_id     uuid REFERENCES identity (id),
            notes                 varchar(1024),
            created_at            timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
            UNIQUE (host, port, kind)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_proxy_pool_state "
        "ON proxy (pool_id, state)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_proxy_bound_identity "
        "ON proxy (bound_identity_id) WHERE bound_identity_id IS NOT NULL"
    )

    # ----- identity.proxy_pool_id + identity.proxy_sticky --------------
    op.execute(
        "ALTER TABLE identity "
        "ADD COLUMN IF NOT EXISTS proxy_pool_id uuid REFERENCES proxy_pool (id)"
    )
    # proxy_sticky nullable on purpose: NULL means "use the source-kind default"
    # (telegram -> sticky, forum -> non-sticky). The collector reads the flag
    # and defaults based on identity.source if NULL. This avoids a forced
    # backfill of existing identity rows.
    op.execute(
        "ALTER TABLE identity "
        "ADD COLUMN IF NOT EXISTS proxy_sticky boolean"
    )


def downgrade_main() -> None:
    op.execute("ALTER TABLE identity DROP COLUMN IF EXISTS proxy_sticky")
    op.execute("ALTER TABLE identity DROP COLUMN IF EXISTS proxy_pool_id")
    op.execute("DROP TABLE IF EXISTS proxy")
    op.execute("DROP TABLE IF EXISTS proxy_pool")
    op.execute("DROP TYPE IF EXISTS proxystate")
    op.execute("DROP TYPE IF EXISTS proxykind")


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
