# SPDX-License-Identifier: AGPL-3.0-or-later
"""stealer_processing table — ULP pipeline per-attachment state — Postgres

Revision ID: 0022_stealer_processing
Revises: 0021_attachment_category
Create Date: 2026-10-23

One row per stealer-marked attachment the StealerProcessorService handled:
state (running/done/failed), creds extracted, error, attempts. Prevents reprocess +
gives the operator visibility. A fresh deploy builds it from model metadata
(``create_all``); this incremental only touches an already-provisioned live DB, hence
``IF NOT EXISTS``. Main DB only.
"""

from __future__ import annotations

from alembic import op

revision = "0022_stealer_processing"
down_revision = "0021_attachment_category"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stealer_processing (
            attachment_id   uuid PRIMARY KEY REFERENCES attachment (id),
            state           varchar NOT NULL DEFAULT 'running',
            creds_extracted integer NOT NULL DEFAULT 0,
            error           varchar,
            attempts        integer NOT NULL DEFAULT 0,
            updated_at      timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_stealer_processing_state "
        "ON stealer_processing (state)"
    )


def downgrade_main() -> None:
    op.execute("DROP TABLE IF EXISTS stealer_processing")


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
