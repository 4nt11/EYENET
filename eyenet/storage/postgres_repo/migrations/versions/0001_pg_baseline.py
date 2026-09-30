# SPDX-License-Identifier: AGPL-3.0-or-later
"""postgres baseline schema

Revision ID: 0001_pg_baseline
Revises:
Create Date: 2026-09-30

The Postgres backend's baseline. Builds the CURRENT model schema (ORM tables via
create_all + the raw DDL that lives outside SQLModel.metadata: the hamming64 UDF,
vector_signature, the partial UNIQUE index). Postgres is a brand-new backend with
no prior revisions, so its baseline is the full current schema — including tables
(forum_crawl_cursor) and columns (audit seq) that reached SQLite as later
revisions.

# ponytail: this uses the LIVE table sets, so head == create_all today (one
# revision, nothing to drift against). FREEZE these into literal frozensets the
# moment you add the FIRST post-baseline Postgres revision, exactly as the SQLite
# baseline froze _MAIN_AT_BASELINE — otherwise a fresh DB would create a later
# table in BOTH the baseline and its own revision (double create).
"""

from __future__ import annotations

from alembic import op

from eyenet.storage.postgres_repo.database import (
    _apply_audit_schema,
    _apply_main_schema,
    _drop_audit_schema,
    _drop_main_schema,
)
from eyenet.storage.sqlite_repo.database import _AUDIT_TABLES, _MAIN_TABLES

revision = "0001_pg_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    _apply_main_schema(op.get_bind(), _MAIN_TABLES)


def downgrade_main() -> None:
    _drop_main_schema(op.get_bind(), _MAIN_TABLES)


def upgrade_audit() -> None:
    _apply_audit_schema(op.get_bind(), _AUDIT_TABLES)


def downgrade_audit() -> None:
    _drop_audit_schema(op.get_bind(), _AUDIT_TABLES)
