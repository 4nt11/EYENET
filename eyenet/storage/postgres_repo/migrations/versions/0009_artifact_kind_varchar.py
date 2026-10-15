# SPDX-License-Identifier: AGPL-3.0-or-later
"""infrastructure_artifact.kind: native enum -> open varchar — Postgres

Revision ID: 0009_artifact_kind_varchar
Revises: 0008_search_document_kind
Create Date: 2026-10-15

Indicator kinds are now OPEN: a match may carry a vendored InfrastructureKind
value or an operator-custom slug (validated at the API as [a-z][a-z0-9_]{1,63}).
The ``infrastructurekind`` native enum can't hold custom values, so the column
becomes a plain varchar. A fresh deploy builds the column as varchar straight
from the (now ``str``) model, so this incremental only touches an already-
provisioned live DB. Main DB only.

``infrastructurekind`` is used by exactly one column (verified against live:
``infrastructure_artifact.kind``), so the type is dropped after the conversion.

Downgrade is LOSSY: it recreates the enum from the current InfrastructureKind
members and casts back. Any custom kind written while open will fail the cast.
"""

from __future__ import annotations

from alembic import op

from eyenet.contracts.enums import InfrastructureKind

revision = "0009_artifact_kind_varchar"
down_revision = "0008_search_document_kind"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    # LOWER(): the native enum stored its NAME labels (uppercase, e.g. ``DOMAIN``),
    # but the canonical open-kind form is the lowercase InfrastructureKind *value*
    # (``domain``) — the form the ruleset emits, the search `kind` facet holds, and
    # BRIDGEABLE_KINDS membership compares against. name.lower() == value for every
    # member, so lowering the labels yields the correct values and keeps old rows,
    # new rows, and the search facet in one representation.
    # ALTER TYPE auto-rebuilds ix_infrastructure_artifact_kind on the column.
    op.execute(
        "ALTER TABLE infrastructure_artifact "
        "ALTER COLUMN kind TYPE VARCHAR USING lower(kind::text)"
    )
    op.execute("DROP TYPE IF EXISTS infrastructurekind")


def downgrade_main() -> None:
    values = ", ".join(f"'{k.value}'" for k in InfrastructureKind)
    op.execute(f"CREATE TYPE infrastructurekind AS ENUM ({values})")
    # Lossy: a custom kind outside InfrastructureKind fails this cast.
    op.execute(
        "ALTER TABLE infrastructure_artifact "
        "ALTER COLUMN kind TYPE infrastructurekind USING kind::infrastructurekind"
    )


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
