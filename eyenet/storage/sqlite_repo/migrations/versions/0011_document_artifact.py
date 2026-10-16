# SPDX-License-Identifier: AGPL-3.0-or-later
"""add document_artifact edge table — SQLite

Revision ID: 0011_document_artifact
Revises: 0010_indicator_ruleset
Create Date: 2026-10-16

SQLite mirror of the Postgres 0011 revision. ``document_artifact`` is net-new (not
in the baseline frozen table set), so, like ``infrastructure_artifact_mention``, it
must be created by an incremental to exist on fresh SQLite DBs built via
``upgrade_to_head``. Created from the model via the shared helper for index/
constraint parity with the no-drift test. Main DB only.
"""

from __future__ import annotations

from alembic import op

from eyenet.storage.sqlite_repo.database import (
    _apply_document_artifact_schema,
    _drop_document_artifact_schema,
)

revision = "0011_document_artifact"
down_revision = "0010_indicator_ruleset"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    _apply_document_artifact_schema(op.get_bind())


def downgrade_main() -> None:
    _drop_document_artifact_schema(op.get_bind())


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
