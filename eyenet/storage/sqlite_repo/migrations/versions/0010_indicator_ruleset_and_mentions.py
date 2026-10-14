# SPDX-License-Identifier: AGPL-3.0-or-later
"""add indicator_rule + infrastructure_artifact_mention, seed vendored rules — SQLite

Revision ID: 0010_indicator_ruleset_and_mentions
Revises: 0009_candidate_dead_state
Create Date: 2026-10-14

SQLite mirror of the Postgres 0007 revision. SQLite is best-effort (Postgres is
the primary backend), but the test suite builds its in-memory DB via
``upgrade_to_head``, so this revision is what makes the new tables + seed exist in
tests and in any file-based SQLite deploy. It reuses the same dialect-neutral
helpers as the Postgres revision — no SQLite-specific logic. Main DB only.
"""

from __future__ import annotations

from alembic import op

from eyenet.storage.sqlite_repo.database import (
    _apply_indicator_schema,
    _drop_indicator_schema,
    seed_indicator_rules,
)

revision = "0010_indicator_ruleset_and_mentions"
down_revision = "0009_candidate_dead_state"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    bind = op.get_bind()
    _apply_indicator_schema(bind)
    seed_indicator_rules(bind)


def downgrade_main() -> None:
    _drop_indicator_schema(op.get_bind())


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
