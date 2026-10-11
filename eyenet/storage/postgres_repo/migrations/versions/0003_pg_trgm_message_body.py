# SPDX-License-Identifier: AGPL-3.0-or-later
"""pg_trgm GIN index for message.body substring search (main DB).

``_body_match`` (incidents/forum/message search) is ``message.body LIKE '%q%'`` —
a seq scan over every message on Postgres. A pg_trgm GIN index makes it index-
backed, same predicate, no code change. body is NOT NULL so no coalesce; the
predicate is case-sensitive (no lower()), so the index is on body directly.

pg_trgm is already created by 0002. Non-concurrent CREATE INDEX here is a no-op on
the live box (built CONCURRENTLY during the session, IF NOT EXISTS) and instant on
a fresh deploy. The index name is in ``_RAW_DDL_OBJECTS`` so autogenerate keeps it.
"""

from __future__ import annotations

from alembic import op

revision = "0003_pg_trgm_message_body"
down_revision = "0002_pg_trgm_search"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_message_body_trgm "
        "ON message USING gin (body gin_trgm_ops)"
    )


def downgrade_main() -> None:
    op.execute("DROP INDEX IF EXISTS ix_message_body_trgm")


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
