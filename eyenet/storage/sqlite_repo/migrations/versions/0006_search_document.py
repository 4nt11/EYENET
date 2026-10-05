# SPDX-License-Identifier: AGPL-3.0-or-later
"""add search_document + FTS5 indexes (global search)

Revision ID: 0006_search_document
Revises: 0005_forum_backfill_page_range
Create Date: 2026-10-05

Additive post-baseline table (GLOBAL_SEARCH.md): the derived cross-entity search
index. Creates the ``search_document`` ORM table plus its two FTS5 external-
content virtual tables (prose + handles) and sync triggers, all via the single
source of truth in ``database.py``. Main DB only; audit is a no-op.
"""

from __future__ import annotations

from alembic import op

from eyenet.storage.sqlite_repo.database import (
    _apply_search_document_schema,
    _drop_search_document_schema,
)

revision = "0006_search_document"
down_revision = "0005_forum_backfill_page_range"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    _apply_search_document_schema(op.get_bind())


def downgrade_main() -> None:
    _drop_search_document_schema(op.get_bind())


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
