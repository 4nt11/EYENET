# SPDX-License-Identifier: AGPL-3.0-or-later
"""stealer_family_override table: operator verdict ground-truth, Postgres

Revision ID: 0024_stealer_family_override
Revises: 0023_proxy_pools
Create Date: 2026-11-18

Operator verdict override on one (archive_sha256, victim_folder) pair.
Overrides win at read time over the classifier verdict and form the
labeled set the scorer gets tuned against (see
development/STEALER_FAMILY_CLASSIFIER_DESIGN.md Phase 7). A fresh deploy
builds it from model metadata (``create_all``); this incremental only
touches an already-provisioned live DB, hence ``IF NOT EXISTS``. Main
DB only.
"""

from __future__ import annotations

from alembic import op

revision = "0024_stealer_family_override"
down_revision = "0023_proxy_pools"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stealer_family_override (
            archive_sha256  varchar(64) NOT NULL,
            victim_folder   varchar(512) NOT NULL,
            slug            varchar(64) NOT NULL,
            reason          varchar(512),
            author_user_id  uuid NOT NULL REFERENCES "system_user" (id),
            created_at      timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
            updated_at      timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
            PRIMARY KEY (archive_sha256, victim_folder)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_stealer_family_override_slug "
        "ON stealer_family_override (slug)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_stealer_family_override_author_user_id "
        "ON stealer_family_override (author_user_id)"
    )


def downgrade_main() -> None:
    op.execute("DROP TABLE IF EXISTS stealer_family_override")


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
