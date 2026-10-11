# SPDX-License-Identifier: AGPL-3.0-or-later
"""Indexes for the audit list/count filters (audit DB).

The operator audit trail (GET /v1/audit?subject_id=...) filters subject_id (and
system_user_id) and orders by ``at DESC``. On Postgres those columns are native
``uuid``; once the text-cast is removed (PostgresRepository._audit_uuid_eq),
a ``(subject_id, at)`` / ``(system_user_id, at)`` btree turns a 3M-row seq scan
(~45s) into an index range scan. Audit DB only; main DB is a no-op.

Built CONCURRENTLY on the live box during the session; IF NOT EXISTS makes this a
no-op there and instant on a fresh deploy. Names are in ``_RAW_DDL_OBJECTS``.
"""

from __future__ import annotations

from alembic import op

revision = "0004_audit_subject_indexes"
down_revision = "0003_pg_trgm_message_body"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    pass


def downgrade_main() -> None:
    pass


def upgrade_audit() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_log_subject_at ON audit_log (subject_id, at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_log_user_at ON audit_log (system_user_id, at)"
    )


def downgrade_audit() -> None:
    op.execute("DROP INDEX IF EXISTS ix_audit_log_user_at")
    op.execute("DROP INDEX IF EXISTS ix_audit_log_subject_at")
