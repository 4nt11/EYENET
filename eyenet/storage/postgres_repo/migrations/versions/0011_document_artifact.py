# SPDX-License-Identifier: AGPL-3.0-or-later
"""document_artifact edge table — Postgres

Revision ID: 0011_document_artifact
Revises: 0010_operator_entities
Create Date: 2026-10-16

Adds ``document_artifact`` — the provenance edge linking an infrastructure artifact
to the document whose extracted text it was found in (the document analogue of
``infrastructure_artifact_mention``). A fresh deploy builds it from the model via
``create_all``, so this incremental only touches an already-provisioned live DB;
the DDL mirrors what ``create_all`` produces and is fully idempotent. Main DB only.
"""

from __future__ import annotations

from alembic import op

from eyenet.storage.sqlite_repo.database import (
    _apply_document_artifact_schema,
    _drop_document_artifact_schema,
)

revision = "0011_document_artifact"
down_revision = "0010_operator_entities"
branch_labels = None
depends_on = None


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    # Created from the model (create_all, idempotent) for index/constraint parity
    # with the no-drift test — same shared helper the SQLite revision uses.
    _apply_document_artifact_schema(op.get_bind())


def downgrade_main() -> None:
    _drop_document_artifact_schema(op.get_bind())


def upgrade_audit() -> None:
    pass


def downgrade_audit() -> None:
    pass
