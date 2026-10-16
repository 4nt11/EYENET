# SPDX-License-Identifier: AGPL-3.0-or-later
"""investigation_graph.edges — Postgres

Revision ID: 0014_investigation_graph_edges
Revises: 0013_entity_note
Create Date: 2026-10-16

Adds the ``edges`` JSON column to ``investigation_graph`` so a saved graph restores
its relationships, not just its nodes. A fresh deploy builds the column from the
model (the 0012 create_all-from-model helper now includes it), so this incremental
only touches an already-provisioned live DB. Main DB only.
"""

from __future__ import annotations

from alembic import op

revision = "0014_investigation_graph_edges"
down_revision = "0013_entity_note"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    op.execute(
        "ALTER TABLE investigation_graph "
        "ADD COLUMN IF NOT EXISTS edges JSON NOT NULL DEFAULT '[]'::json"
    )


def downgrade_main() -> None:
    op.execute("ALTER TABLE investigation_graph DROP COLUMN IF EXISTS edges")


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
