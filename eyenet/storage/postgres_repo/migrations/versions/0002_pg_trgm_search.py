# SPDX-License-Identifier: AGPL-3.0-or-later
"""pg_trgm GIN indexes for substring search on search_document (main DB).

The search layer is substring LIKE everywhere (``LOWER(col) LIKE '%q%'`` via
``_search_predicate``); on Postgres that was a seq scan over every row. pg_trgm
GIN expression indexes make the EXACT existing predicates index-backed with no
query-layer or semantic change (measured ~2100ms -> ~190ms on a 875k-row corpus).

Expression indexes must match the query expressions in ``_search_predicate``:
``lower(haystack)`` and ``lower(coalesce(handles, ''))``. Audit DB: no-op.

Non-concurrent CREATE INDEX here is fine: a fresh deploy builds them on an empty
table instantly, and the one-shot cutover already built them CONCURRENTLY on the
live box, so IF NOT EXISTS makes this a no-op there. The index names are listed
in ``_RAW_DDL_OBJECTS`` so --autogenerate never proposes dropping them.
"""

from __future__ import annotations

from alembic import op

revision = "0002_pg_trgm_search"
down_revision = "0001_pg_baseline"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_search_document_haystack_trgm "
        "ON search_document USING gin (lower(haystack) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_search_document_handles_trgm "
        "ON search_document USING gin (lower(coalesce(handles, '')) gin_trgm_ops)"
    )


def downgrade_main() -> None:
    op.execute("DROP INDEX IF EXISTS ix_search_document_handles_trgm")
    op.execute("DROP INDEX IF EXISTS ix_search_document_haystack_trgm")
    # Leave the pg_trgm extension in place; other objects may use it.


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
