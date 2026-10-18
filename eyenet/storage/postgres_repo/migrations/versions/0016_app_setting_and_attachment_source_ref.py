# SPDX-License-Identifier: AGPL-3.0-or-later
"""app_setting KV table + attachment.source_ref — Postgres

Revision ID: 0016_app_setting_source_ref
Revises: 0015_search_document_tier
Create Date: 2026-10-18

Fresh deploys get both from create_all off the model; this incremental is for the
already-provisioned live DB. Additive only:
- ``app_setting`` (runtime operator knobs, e.g. ``telegram.attachment_max_bytes``).
- ``attachment.source_ref`` (operator retrieval link for blobs not stored on disk,
  e.g. files over the download size gate). Nullable, no backfill — existing rows had
  no link captured; the collector sets it going forward and the backfill job fills it
  for re-fetched shells.
Main DB only.
"""

from __future__ import annotations

from alembic import op

from eyenet.storage.sqlite_repo.database import (
    _apply_app_setting_schema,
    _drop_app_setting_schema,
)

revision = "0016_app_setting_source_ref"
down_revision = "0015_search_document_tier"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    # Table from the model (create_all, idempotent) so fresh + live agree and the
    # no-drift test stays quiet; the column add is a plain idempotent ALTER.
    _apply_app_setting_schema(op.get_bind())
    op.execute("ALTER TABLE attachment ADD COLUMN IF NOT EXISTS source_ref VARCHAR")


def downgrade_main() -> None:
    op.execute("ALTER TABLE attachment DROP COLUMN IF EXISTS source_ref")
    _drop_app_setting_schema(op.get_bind())


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
