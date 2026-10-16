# SPDX-License-Identifier: AGPL-3.0-or-later
"""per-entity notes: entity_note — Postgres

Revision ID: 0013_entity_note
Revises: 0012_saved_graphs
Create Date: 2026-10-16

Net-new table backing the canvas Notes tab (one note per (entity_type, entity_id)).
Created from the model via the shared helper (create_all, idempotent) for parity
with the no-drift test. Main DB only.
"""

from __future__ import annotations

from alembic import op

from eyenet.storage.sqlite_repo.database import (
    _apply_entity_note_schema,
    _drop_entity_note_schema,
)

revision = "0013_entity_note"
down_revision = "0012_saved_graphs"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    _apply_entity_note_schema(op.get_bind())


def downgrade_main() -> None:
    _drop_entity_note_schema(op.get_bind())


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
