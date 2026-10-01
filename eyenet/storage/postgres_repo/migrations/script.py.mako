# SPDX-License-Identifier: AGPL-3.0-or-later
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
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

% for db_name in ["main", "audit"]:

def upgrade_${db_name}() -> None:
    ${context.get(f"{db_name}_upgrades", "pass")}


def downgrade_${db_name}() -> None:
    ${context.get(f"{db_name}_downgrades", "pass")}
% endfor
