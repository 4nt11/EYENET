# SPDX-License-Identifier: AGPL-3.0-or-later
"""operator-asserted entities: SourceKind.OPERATOR + provenance columns — Postgres

Revision ID: 0010_operator_entities
Revises: 0009_artifact_kind_varchar
Create Date: 2026-10-16

Adds the exploration-canvas "operator entity" support:
- ``SourceKind`` gains ``OPERATOR`` (native enum ``sourcekind`` ADD VALUE) — the
  synthetic source that owns hand-created actors/groups.
- ``provenance`` varchar (``'collected'`` default) on ``actor``, ``group_`` and
  ``infrastructure_artifact``, marking operator-asserted rows.

A fresh deploy builds all of this straight from the model metadata (``create_all``),
so this incremental only touches an already-provisioned live DB — hence every
statement is idempotent (``IF NOT EXISTS``). Main DB only.
"""

from __future__ import annotations

from alembic import op

revision = "0010_operator_entities"
down_revision = "0009_artifact_kind_varchar"
branch_labels = None
depends_on = None

_PROVENANCE_TABLES = ("actor", "group_", "infrastructure_artifact")


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    # ADD VALUE historically cannot run inside a transaction block; autocommit_block
    # is safe on every PG version. IF NOT EXISTS makes it a no-op on a fresh deploy
    # where create_all already built the enum with OPERATOR.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE sourcekind ADD VALUE IF NOT EXISTS 'OPERATOR'")
    for table in _PROVENANCE_TABLES:
        op.execute(
            f"ALTER TABLE {table} "
            "ADD COLUMN IF NOT EXISTS provenance VARCHAR NOT NULL DEFAULT 'collected'"
        )
    # Index names mirror SQLAlchemy's ix_<table>_<col> convention (group_ -> double _).
    op.execute("CREATE INDEX IF NOT EXISTS ix_actor_provenance ON actor (provenance)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_group__provenance ON group_ (provenance)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_infrastructure_artifact_provenance "
        "ON infrastructure_artifact (provenance)"
    )


def downgrade_main() -> None:
    # The enum value is NOT removed: PG has no ALTER TYPE ... DROP VALUE. Dropping
    # the columns is enough to undo the operator-entity feature.
    op.execute("DROP INDEX IF EXISTS ix_actor_provenance")
    op.execute("DROP INDEX IF EXISTS ix_group__provenance")
    op.execute("DROP INDEX IF EXISTS ix_infrastructure_artifact_provenance")
    for table in _PROVENANCE_TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS provenance")


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
