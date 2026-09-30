# SPDX-License-Identifier: AGPL-3.0-or-later
"""baseline schema (v0.1.0)

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-30

The v0.1.0 baseline. Reproduces EXACTLY what the legacy ``create_all`` bootstrap
built, by delegating to the single source of truth in ``database.py`` — the ORM
tables (``SQLModel.metadata``) PLUS the raw DDL that lives outside it (the FTS5
index + triggers, ``vector_signature``, the partial UNIQUE index). Writing the
baseline this way (rather than transcribing every column) guarantees the
migrated schema is byte-for-byte the create_all schema; the equivalence test
pins that. Every subsequent revision is a normal ``--autogenerate`` diff.

An EXISTING populated DB is brought under Alembic with ``alembic stamp
0001_baseline`` (never an upgrade — the tables already exist). A fresh DB runs
this upgrade.
"""

from __future__ import annotations

from alembic import op

from eyenet.storage.sqlite_repo.database import (
    _apply_audit_schema,
    _apply_main_schema,
    _drop_audit_schema,
    _drop_main_schema,
)

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    _apply_main_schema(op.get_bind())


def downgrade_main() -> None:
    _drop_main_schema(op.get_bind())


def upgrade_audit() -> None:
    _apply_audit_schema(op.get_bind())


def downgrade_audit() -> None:
    _drop_audit_schema(op.get_bind())
