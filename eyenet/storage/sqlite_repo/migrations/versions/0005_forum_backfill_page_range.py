# SPDX-License-Identifier: AGPL-3.0-or-later
"""add forum_backfill_request page range (from_page/to_page)

Revision ID: 0005_forum_backfill_page_range
Revises: 0004_forum_thread_alias
Create Date: 2026-10-05

Adds ``from_page``/``to_page`` so a backfill can target a category page RANGE
(the one-shot "re-sweep page 2-3 now" override) instead of only a whole thread.
Null = a thread backfill.

EXISTENCE-GUARDED, same posture as 0003_audit_seq: the 0001 baseline builds the
table via live ``create_all``, so a FRESH DB already has these columns before
this revision runs and every step here is skipped (keeping ``head`` byte-for-byte
equal to create_all, per the baseline equivalence test). Only an EXISTING DB
stamped at an earlier revision actually gets the columns added. Main DB only;
audit is a no-op.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_forum_backfill_page_range"
down_revision = "0004_forum_thread_alias"
branch_labels = None
depends_on = None

_TABLE = "forum_backfill_request"
_NEW_COLUMNS = ("from_page", "to_page")


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    for name in _NEW_COLUMNS:
        if name in existing:  # fresh DB: create_all at baseline already made it
            continue
        # Nullable ADD COLUMN: native in SQLite, no table rebuild.
        op.add_column(_TABLE, sa.Column(name, sa.Integer(), nullable=True))


def downgrade_main() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    for name in reversed(_NEW_COLUMNS):
        if name in existing:
            op.drop_column(_TABLE, name)


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
