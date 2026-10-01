# SPDX-License-Identifier: AGPL-3.0-or-later
"""add forum_thread_alias

Revision ID: 0004_forum_thread_alias
Revises: 0003_audit_seq
Create Date: 2026-09-30

Additive: maps a thread's canonical tid to its first-seen group key so a
moved/re-slugged thread dedupes to the original. Main DB only; audit is a no-op.
"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "0004_forum_thread_alias"
down_revision = "0003_audit_seq"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    op.create_table(
        "forum_thread_alias",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_tid", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("platform_groupid", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "canonical_tid", name="uq_forum_thread_alias"),
    )
    with op.batch_alter_table("forum_thread_alias", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_forum_thread_alias_canonical_tid"), ["canonical_tid"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_forum_thread_alias_source_id"), ["source_id"], unique=False
        )


def downgrade_main() -> None:
    with op.batch_alter_table("forum_thread_alias", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_forum_thread_alias_source_id"))
        batch_op.drop_index(batch_op.f("ix_forum_thread_alias_canonical_tid"))

    op.drop_table("forum_thread_alias")


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
