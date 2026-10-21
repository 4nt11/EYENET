# SPDX-License-Identifier: AGPL-3.0-or-later
"""group_ reincarnation lineage: lineage_id + group_iteration — Postgres

Revision ID: 0018_group_lineage
Revises: 0017_groupkind_guild
Create Date: 2026-10-21

A channel/board reincarnates (nuked and recreated) with a new external
platform_groupid, so each incarnation is a distinct ``group_`` row. ``lineage_id``
is the stable logical-group key shared by every incarnation (== ``id`` for a root),
and ``group_iteration`` is the 1-based version within it.

A fresh deploy builds both columns from the model metadata (``create_all``), so this
incremental only touches an already-provisioned live DB, hence ``IF NOT EXISTS`` (a
no-op on fresh). The backfill roots every existing group at itself (lineage_id = id,
iteration stays 1); chaining specific historical reincarnations is a separate operator
data fix, not a schema migration. Main DB only.
"""

from __future__ import annotations

from alembic import op

revision = "0018_group_lineage"
down_revision = "0017_groupkind_guild"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    op.execute("ALTER TABLE group_ ADD COLUMN IF NOT EXISTS lineage_id uuid")
    op.execute(
        "ALTER TABLE group_ ADD COLUMN IF NOT EXISTS group_iteration integer NOT NULL DEFAULT 1"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_group__lineage_id ON group_ (lineage_id)")
    # Every existing group roots its own lineage (no-op for rows a fresh create_all
    # already defaulted to NULL then this stamps; idempotent on re-run).
    op.execute("UPDATE group_ SET lineage_id = id WHERE lineage_id IS NULL")


def downgrade_main() -> None:
    op.execute("DROP INDEX IF EXISTS ix_group__lineage_id")
    op.execute("ALTER TABLE group_ DROP COLUMN IF EXISTS group_iteration")
    op.execute("ALTER TABLE group_ DROP COLUMN IF EXISTS lineage_id")


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
