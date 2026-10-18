# SPDX-License-Identifier: AGPL-3.0-or-later
"""add search_document.tier (effective sensitivity tier, clearance gate) — Postgres

Revision ID: 0015_search_document_tier
Revises: 0014_investigation_graph_edges
Create Date: 2026-10-18

``search_document`` is rebuilt from the model on a fresh deploy (create_all picks up
the new column + its index), so this incremental is for an already-provisioned live DB:
ADD COLUMN IF NOT EXISTS tier + the matching ``ix_search_document_tier`` index (same
name create_all generates, so fresh and live agree and --autogenerate stays empty).

Documents were indexed into search_document WITHOUT a tier, so an uncleared caller
could full-text search a classified document's title/body through the search box — a
clearance bypass. The column defaults to 'normal' (every untiered entity stays visible);
the data step then backfills existing DOCUMENT rows with their effective tier
(operator override wins over classifier), closing the leak atomically with the add
rather than leaving a window until the next reindex. Main DB only.
"""

from __future__ import annotations

from alembic import op

revision = "0015_search_document_tier"
down_revision = "0014_investigation_graph_edges"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    op.execute(
        "ALTER TABLE search_document ADD COLUMN IF NOT EXISTS tier VARCHAR NOT NULL DEFAULT 'normal'"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_search_document_tier ON search_document (tier)")
    # Backfill existing document rows from the source of truth. PG stores the native
    # SensitivityTier enum as its member NAME (uppercase), so ::text + LOWER() yields the
    # 'normal'/'restricted'/'classified' value the column (and the search filter) expect.
    op.execute(
        """
        UPDATE search_document AS sd
        SET tier = LOWER(COALESCE(d.operator_tier_override, d.classifier_tier)::text)
        FROM document AS d
        WHERE sd.entity_type = 'document' AND sd.entity_id = d.id
        """
    )


def downgrade_main() -> None:
    op.execute("DROP INDEX IF EXISTS ix_search_document_tier")
    op.execute("ALTER TABLE search_document DROP COLUMN IF EXISTS tier")


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
