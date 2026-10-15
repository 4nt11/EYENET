# SPDX-License-Identifier: AGPL-3.0-or-later
"""add search_document.kind (sub-type facet, e.g. artifact InfrastructureKind) — Postgres

Revision ID: 0008_search_document_kind
Revises: 0007_indicator_ruleset_and_mentions
Create Date: 2026-10-14

``search_document`` is rebuilt from the model on a fresh deploy (the search-doc
migration create_all picks up the new column + its index), so this incremental
exists only for an already-provisioned live DB: ADD COLUMN IF NOT EXISTS + the
matching ``ix_search_document_kind`` index (same name create_all generates, so
fresh and live agree and --autogenerate stays empty). Main DB only.
"""

from __future__ import annotations

from alembic import op

revision = "0008_search_document_kind"
down_revision = "0007_indicator_ruleset_and_mentions"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    op.execute("ALTER TABLE search_document ADD COLUMN IF NOT EXISTS kind VARCHAR")
    op.execute("CREATE INDEX IF NOT EXISTS ix_search_document_kind ON search_document (kind)")


def downgrade_main() -> None:
    op.execute("DROP INDEX IF EXISTS ix_search_document_kind")
    op.execute("ALTER TABLE search_document DROP COLUMN IF EXISTS kind")


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
