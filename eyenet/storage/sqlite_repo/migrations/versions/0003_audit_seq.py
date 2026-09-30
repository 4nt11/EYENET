# SPDX-License-Identifier: AGPL-3.0-or-later
"""add portable monotonic seq to the two audit-db hash chains

Revision ID: 0003_audit_seq
Revises: 0002_forum_crawl_cursor
Create Date: 2026-09-30

Adds ``seq`` (monotonic insertion order) to ``audit_log`` and
``file_access_journal`` so the hash chains are walked by a PORTABLE column
instead of SQLite's implicit ``rowid`` (which Postgres lacks). This unblocks the
Postgres backend, whose chain reads use the same ``ORDER BY seq``.

EXISTENCE-GUARDED. The ``0001`` baseline builds these tables via live
``create_all``, so a FRESH DB already has ``seq`` (and its index) before this
revision runs — for those, every step here is skipped and the revision is a
no-op, keeping ``head`` byte-for-byte equal to ``create_all`` (the baseline
equivalence test). Only an EXISTING DB stamped at an earlier revision actually
gets the column added and backfilled here.

Backfill sets ``seq = rowid``: rowid IS the existing insertion order on these
append-only tables, so the chain linkage order is preserved exactly. New rows
continue from MAX(seq)+1 in the serialized append. Audit-db only; main is a
no-op.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_audit_seq"
down_revision = "0002_forum_crawl_cursor"
branch_labels = None
depends_on = None

_CHAIN_TABLES = ("audit_log", "file_access_journal")


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    pass


def downgrade_main() -> None:
    pass


def upgrade_audit() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in _CHAIN_TABLES:
        existing = {c["name"] for c in inspector.get_columns(table)}
        if "seq" in existing:
            # Fresh DB: create_all at the baseline already made seq + its index.
            continue
        # SQLite supports a native ADD COLUMN for a nullable column (no table
        # rebuild needed), so a plain op.add_column is fine here.
        op.add_column(table, sa.Column("seq", sa.Integer(), nullable=True))
        # rowid is the real insertion order on this append-only chain.
        op.execute(f"UPDATE {table} SET seq = rowid")  # noqa: S608 — table is a fixed literal
        op.create_index(f"ix_{table}_seq", table, ["seq"], unique=False)


def downgrade_audit() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in _CHAIN_TABLES:
        existing = {c["name"] for c in inspector.get_columns(table)}
        if "seq" not in existing:
            continue
        indexes = {ix["name"] for ix in inspector.get_indexes(table)}
        if f"ix_{table}_seq" in indexes:
            op.drop_index(f"ix_{table}_seq", table_name=table)
        op.drop_column(table, "seq")
