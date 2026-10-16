# SPDX-License-Identifier: AGPL-3.0-or-later
"""saved graphs: investigation_graph + investigation_graph_node — SQLite

Revision ID: 0012_saved_graphs
Revises: 0011_document_artifact
Create Date: 2026-10-16

SQLite mirror of the Postgres 0012 revision. Net-new tables (not in the baseline
frozen set), created from the model via the shared helper for parity with the
no-drift test. Main DB only.
"""

from __future__ import annotations

from alembic import op

from eyenet.storage.sqlite_repo.database import (
    _apply_saved_graph_schema,
    _drop_saved_graph_schema,
)

revision = "0012_saved_graphs"
down_revision = "0011_document_artifact"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    _apply_saved_graph_schema(op.get_bind())


def downgrade_main() -> None:
    _drop_saved_graph_schema(op.get_bind())


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
