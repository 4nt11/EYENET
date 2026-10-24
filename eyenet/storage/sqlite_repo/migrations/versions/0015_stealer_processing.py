# SPDX-License-Identifier: AGPL-3.0-or-later
"""stealer_processing table — ULP pipeline per-attachment state — SQLite

Revision ID: 0015_stealer_processing
Revises: 0014_app_setting
Create Date: 2026-10-23

SQLite mirror of the Postgres 0022 stealer_processing table (the backends' migration
trees number independently). Net-new table (not in the baseline frozen set), created
from the model via the shared helper for parity with the no-drift test. The companion
attachment.category column rides the model-driven baseline create_all, so it needs no
SQLite column migration. Main DB only.
"""

from __future__ import annotations

from alembic import op

from eyenet.storage.sqlite_repo.database import (
    _apply_stealer_processing_schema,
    _drop_stealer_processing_schema,
)

revision = "0015_stealer_processing"
down_revision = "0014_app_setting"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    _apply_stealer_processing_schema(op.get_bind())


def downgrade_main() -> None:
    _drop_stealer_processing_schema(op.get_bind())


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
