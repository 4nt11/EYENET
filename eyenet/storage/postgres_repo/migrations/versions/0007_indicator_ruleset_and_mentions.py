# SPDX-License-Identifier: AGPL-3.0-or-later
"""add indicator_rule + infrastructure_artifact_mention, seed vendored rules — Postgres

Revision ID: 0007_indicator_ruleset
Revises: 0006_candidate_backfill_on_join
Create Date: 2026-10-14

Two additive post-baseline tables + a data seed:

- ``infrastructure_artifact_mention`` — per-message provenance edge for extracted
  artifacts (the dedup store ``infrastructure_artifact`` had no writer linking it
  back to a message).
- ``indicator_rule`` — the operator-tunable extraction ruleset (Wazuh-style
  vendored defaults + enable/disable), seeded here with the default catalog.

Tables are created from the model (``_apply_indicator_schema``) for index parity
with the no-drift test; ``create_all`` is idempotent so a fresh deploy whose
baseline already built them is a no-op. The seed is dialect-neutral and inserts
only missing rows, so it never clobbers an operator ``enabled`` toggle. Main DB
only; audit is a no-op.
"""

from __future__ import annotations

from alembic import op

from eyenet.storage.sqlite_repo.database import (
    _apply_indicator_schema,
    _drop_indicator_schema,
    seed_indicator_rules,
)

revision = "0007_indicator_ruleset"
down_revision = "0006_candidate_backfill_on_join"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    bind = op.get_bind()
    _apply_indicator_schema(bind)
    seed_indicator_rules(bind)


def downgrade_main() -> None:
    _drop_indicator_schema(op.get_bind())


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
