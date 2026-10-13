# SPDX-License-Identifier: AGPL-3.0-or-later
"""add group_candidate.backfill_on_join (per-join backfill choice) — Postgres

Revision ID: 0006_candidate_backfill_on_join
Revises: 0005_incident_nonblank_body
Create Date: 2026-10-13

The operator's per-join backfill choice (the /groups/join checkbox) is persisted
on the candidate at APPROVED time and read back when the supervisor builds
JoinGroupCommand. NULL = unspecified → the collector falls back to its own
backfill_on_join default.

This column is new in the model, so the baseline (create_all of live metadata)
already creates it on a FRESH database. This incremental exists only for an
already-provisioned DB that is past the baseline (the live operating DB), hence
``ADD COLUMN IF NOT EXISTS``: it adds the column on the live DB and is a harmless
no-op on a fresh deploy where create_all made it. Main DB only; additive, no
table rewrite.
"""

from __future__ import annotations

from alembic import op

revision = "0006_candidate_backfill_on_join"
down_revision = "0005_incident_nonblank_body"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    op.execute("ALTER TABLE group_candidate ADD COLUMN IF NOT EXISTS backfill_on_join BOOLEAN")


def downgrade_main() -> None:
    op.execute("ALTER TABLE group_candidate DROP COLUMN IF EXISTS backfill_on_join")


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
