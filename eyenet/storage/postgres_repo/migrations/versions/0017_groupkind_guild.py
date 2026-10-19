# SPDX-License-Identifier: AGPL-3.0-or-later
"""GroupKind.GUILD: a server/community container kind — Postgres

Revision ID: 0017_groupkind_guild
Revises: 0016_app_setting_source_ref
Create Date: 2026-10-19

Adds ``GUILD`` to the native ``groupkind`` enum: the container kind for a Discord
guild (and, forward, an IRC network / Matrix space), distinct from its channels.
This is what lets an actor-in-guild ``membership`` row (rank) hang off a real
``group_`` node instead of a mislabelled one.

A fresh deploy builds the enum with GUILD straight from the model metadata
(``create_all``), so this incremental only touches an already-provisioned live DB,
hence ``IF NOT EXISTS`` (a no-op on fresh). Main DB only.
"""

from __future__ import annotations

from alembic import op

revision = "0017_groupkind_guild"
down_revision = "0016_app_setting_source_ref"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    # ADD VALUE cannot run inside a transaction block; autocommit_block is safe on
    # every PG version. IF NOT EXISTS makes it a no-op on a fresh deploy where
    # create_all already built the enum with GUILD.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE groupkind ADD VALUE IF NOT EXISTS 'GUILD'")


def downgrade_main() -> None:
    # PG has no ALTER TYPE ... DROP VALUE; the enum value stays. No-op.
    pass


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
