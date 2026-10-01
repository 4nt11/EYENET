# SPDX-License-Identifier: AGPL-3.0-or-later
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Multi-database revision (main.db + audit.db). ``env.py`` runs this once per
engine, dispatching to the matching ``upgrade_<name>`` / ``downgrade_<name>``.
A revision that only touches one DB leaves the other half as ``pass``.
"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op

${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    ${context.get("main_upgrades", "pass")}


def downgrade_main() -> None:
    ${context.get("main_downgrades", "pass")}


def upgrade_audit() -> None:
    ${context.get("audit_upgrades", "pass")}


def downgrade_audit() -> None:
    ${context.get("audit_downgrades", "pass")}
