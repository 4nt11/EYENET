# SPDX-License-Identifier: AGPL-3.0-or-later
"""group_ collection class: category — Postgres

Revision ID: 0019_group_category
Revises: 0018_group_lineage
Create Date: 2026-10-23

Marks a group's collection class (e.g. "stealer_logs"), which dispatches
collector/pipeline behavior (attachment-size-gate bypass + routing to the stealer
pipeline). Open varchar, no DB enum, so a new class needs no migration; NULL means
ordinary collection.

A fresh deploy builds the column from the model metadata (``create_all``), so this
incremental only touches an already-provisioned live DB, hence ``IF NOT EXISTS`` (a
no-op on fresh). Main DB only.
"""

from __future__ import annotations

from alembic import op

revision = "0019_group_category"
down_revision = "0018_group_lineage"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    op.execute("ALTER TABLE group_ ADD COLUMN IF NOT EXISTS category varchar")
    op.execute("CREATE INDEX IF NOT EXISTS ix_group__category ON group_ (category)")


def downgrade_main() -> None:
    op.execute("DROP INDEX IF EXISTS ix_group__category")
    op.execute("ALTER TABLE group_ DROP COLUMN IF EXISTS category")


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
