# SPDX-License-Identifier: AGPL-3.0-or-later
"""add asserted_edge (operator-mapped graph edges)

Revision ID: 0008_asserted_edge
Revises: 0007_search_document_fields
Create Date: 2026-10-05

Additive post-baseline table (GLOBAL_SEARCH.md §10.4): durable, audited
operator-asserted relationships drawn on the search graph. Main DB only; audit is
a no-op. Created via the single source of truth in ``database.py`` for index
parity with the model.
"""

from __future__ import annotations

from alembic import op

from eyenet.storage.sqlite_repo.database import (
    _apply_asserted_edge_schema,
    _drop_asserted_edge_schema,
)

revision = "0008_asserted_edge"
down_revision = "0007_search_document_fields"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    _apply_asserted_edge_schema(op.get_bind())


def downgrade_main() -> None:
    _drop_asserted_edge_schema(op.get_bind())


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
