# SPDX-License-Identifier: AGPL-3.0-or-later
"""add DEAD to the group_candidate state CHECK

Revision ID: 0009_candidate_dead_state
Revises: 0008_asserted_edge
Create Date: 2026-10-10

A group nuked platform-side (deleted / TOS-banned / renamed) is now a terminal
``DEAD`` candidate state (see CandidateState.DEAD): the collector detects the
unambiguous resolve failure, transitions the candidate, and stops monitoring.
The column stores the enum NAME, so the ``ck_candidate_state`` CHECK must admit
'DEAD'. SQLite cannot ALTER a CHECK in place — batch recreate. Main DB only;
audit is a no-op.
"""

from __future__ import annotations

from alembic import op

revision = "0009_candidate_dead_state"
down_revision = "0008_asserted_edge"
branch_labels = None
depends_on = None

_STATES_WITH_DEAD = (
    "state IN ('DISCOVERED','QUEUED','APPROVED','JOINING',"
    "'JOINED','REQUESTED','REJECTED','FAILED','PARKED','DEAD')"
)
_STATES_WITHOUT_DEAD = (
    "state IN ('DISCOVERED','QUEUED','APPROVED','JOINING',"
    "'JOINED','REQUESTED','REJECTED','FAILED','PARKED')"
)


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    with op.batch_alter_table("group_candidate", schema=None) as batch_op:
        batch_op.drop_constraint("ck_candidate_state", type_="check")
        batch_op.create_check_constraint("ck_candidate_state", _STATES_WITH_DEAD)


def downgrade_main() -> None:
    # Safe only if no row is in the DEAD state (the old CHECK would reject it).
    op.execute("DELETE FROM group_candidate WHERE state = 'DEAD'")
    with op.batch_alter_table("group_candidate", schema=None) as batch_op:
        batch_op.drop_constraint("ck_candidate_state", type_="check")
        batch_op.create_check_constraint("ck_candidate_state", _STATES_WITHOUT_DEAD)


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
