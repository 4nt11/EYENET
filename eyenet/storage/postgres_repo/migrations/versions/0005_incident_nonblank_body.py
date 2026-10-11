# SPDX-License-Identifier: AGPL-3.0-or-later
"""Partial index for the incidents feed's exclude_bodyless count (main DB).

GET /v1/incidents?include_total=1 always filters exclude_bodyless, i.e.
``incident JOIN message WHERE length(trim(body)) > 0``. The COUNT re-evaluated the
per-row trim over every joined message (~937ms). A partial index on message(id)
for non-blank bodies turns the count into a merge of two index-only scans
(message + ix_incident_message_id), no heap reads, no trim: ~937ms -> ~44ms.

The predicate matches the query's ``length(trim(body)) > 0`` (trim == btrim). Built
CONCURRENTLY on the live box during the session; IF NOT EXISTS is a no-op there and
instant on a fresh deploy. Index name is in ``_RAW_DDL_OBJECTS``.
"""

from __future__ import annotations

from alembic import op

revision = "0005_incident_nonblank_body"
down_revision = "0004_audit_subject_indexes"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_message_nonblank_body "
        "ON message (id) WHERE length(btrim(body)) > 0"
    )


def downgrade_main() -> None:
    op.execute("DROP INDEX IF EXISTS ix_message_nonblank_body")


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
