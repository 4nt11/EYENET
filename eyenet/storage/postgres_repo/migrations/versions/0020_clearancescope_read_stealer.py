# SPDX-License-Identifier: AGPL-3.0-or-later
"""ClearanceScope.READ_STEALER: time-bounded stealer-corpus read — Postgres

Revision ID: 0020_clearancescope_read_stealer
Revises: 0019_group_category
Create Date: 2026-10-23

Adds ``READ_STEALER`` to the native ``clearancescope`` enum. The stealer-log corpus
is victim-credential data, so its READ gate rides the §4.8 clearance lifecycle
(bounded expiry + mandatory reason + court-defensible audit) rather than a permanent
baseline — a client's access lapses with their subscription, an analyst's is
justified and expiring. (write/admin:stealer are separate permanent capability
grants, not clearance.)

The PG enum label is the member NAME (``READ_STEALER``), per SQLAlchemy native-enum
rendering. A fresh deploy builds the enum with the member straight from the model
metadata (``create_all``), so this incremental only touches an already-provisioned
live DB, hence ``IF NOT EXISTS`` (a no-op on fresh). Main DB only.
"""

from __future__ import annotations

from alembic import op

revision = "0020_clearancescope_read_stealer"
down_revision = "0019_group_category"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    # ADD VALUE cannot run inside a transaction block; autocommit_block is safe on
    # every PG version. IF NOT EXISTS makes it a no-op on a fresh deploy where
    # create_all already built the enum with READ_STEALER.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE clearancescope ADD VALUE IF NOT EXISTS 'READ_STEALER'")


def downgrade_main() -> None:
    # PG has no ALTER TYPE ... DROP VALUE; the enum value stays. No-op.
    pass


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
