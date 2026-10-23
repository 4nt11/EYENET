# SPDX-License-Identifier: AGPL-3.0-or-later
"""attachment collection class: category — Postgres

Revision ID: 0021_attachment_category
Revises: 0020_clearancescope_read_stealer
Create Date: 2026-10-23

Marks an attachment's collection class (e.g. "stealer_logs") — the processing-queue
marker the ULP extraction pipeline consumes. Auto-set at capture for archive drops on
stealer-marked channels. Open varchar, no DB enum (a new class needs no migration);
NULL means an ordinary attachment.

A fresh deploy builds the column from the model metadata (``create_all``); this
incremental only touches an already-provisioned live DB, hence ``IF NOT EXISTS`` (a
no-op on fresh). Main DB only.
"""

from __future__ import annotations

from alembic import op

revision = "0021_attachment_category"
down_revision = "0020_clearancescope_read_stealer"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    op.execute("ALTER TABLE attachment ADD COLUMN IF NOT EXISTS category varchar")
    op.execute("CREATE INDEX IF NOT EXISTS ix_attachment_category ON attachment (category)")


def downgrade_main() -> None:
    op.execute("DROP INDEX IF EXISTS ix_attachment_category")
    op.execute("ALTER TABLE attachment DROP COLUMN IF EXISTS category")


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
