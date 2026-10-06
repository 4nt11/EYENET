# SPDX-License-Identifier: AGPL-3.0-or-later
"""add search_document.fields (structured per-entity fields)

Revision ID: 0007_search_document_fields
Revises: 0006_search_document
Create Date: 2026-10-05

Adds the ``fields`` JSON column (the Kibana ``_source`` analog) driving
configurable result columns + the future query-DSL field predicates
(GLOBAL_SEARCH.md §10.2).

EXISTENCE-GUARDED (same posture as 0005): 0006 builds search_document via live
``create_all``, so a FRESH DB already has ``fields`` (it is on the model) before
this runs and the step is skipped — keeping ``head`` byte-for-byte equal to
create_all. Only an EXISTING DB stamped at 0006 (the deployed prod DB) actually
gets the column added. Main DB only; audit is a no-op.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_search_document_fields"
down_revision = "0006_search_document"
branch_labels = None
depends_on = None

_TABLE = "search_document"
_COLUMN = "fields"


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    if _COLUMN not in existing:  # fresh DB: create_all at 0006 already made it
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.JSON(), nullable=True))


def downgrade_main() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    if _COLUMN in existing:
        op.drop_column(_TABLE, _COLUMN)


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
