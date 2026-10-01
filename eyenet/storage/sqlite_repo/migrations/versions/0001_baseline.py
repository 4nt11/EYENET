# SPDX-License-Identifier: AGPL-3.0-or-later
"""baseline schema (v0.1.0)

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-30

The v0.1.0 baseline. Reproduces EXACTLY what the legacy ``create_all`` bootstrap
built, by delegating to the single source of truth in ``database.py`` — the ORM
tables (``SQLModel.metadata``) PLUS the raw DDL that lives outside it (the FTS5
index + triggers, ``vector_signature``, the partial UNIQUE index). Writing the
baseline this way (rather than transcribing every column) guarantees the
migrated schema is byte-for-byte the create_all schema; the equivalence test
pins that. Every subsequent revision is a normal ``--autogenerate`` diff.

An EXISTING populated DB is brought under Alembic with ``alembic stamp
0001_baseline`` (never an upgrade — the tables already exist). A fresh DB runs
this upgrade.
"""

from __future__ import annotations

from alembic import op

from eyenet.storage.sqlite_repo.database import (
    _apply_audit_schema,
    _apply_main_schema,
    _drop_audit_schema,
    _drop_main_schema,
)

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

# FROZEN at the v0.1.0 cutover. This list does NOT track the live
# ``_MAIN_TABLES`` / ``_AUDIT_TABLES`` frozensets — a table added to the models
# after the baseline gets its OWN revision (see 0002+), it must never be added
# here, or a fresh DB would create it in 0001 AND its own revision (double
# create). ``forum_crawl_cursor`` is the first such post-baseline table.
_MAIN_AT_BASELINE = frozenset(
    {
        "actor", "actor_alias_history", "actor_artifact", "actor_relation",
        "attachment", "audit_anchor", "case_collaborator", "case_member", "case_v2",
        "collector", "collector_group_membership", "content_template", "corpus_cursor",
        "document", "engagement_authorization", "feedback_pair", "forum_backfill_request",
        "forum_reply_request", "forum_thread_link", "graph_edge", "graph_node", "group_",
        "group_access_artifact", "group_candidate", "group_candidate_mention",
        "group_snapshot", "idempotency_record", "identity", "identity_event_log",
        "identity_label", "incident", "incident_label", "incident_rule",
        "infrastructure_artifact", "jwt_denylist", "linkage", "linkage_event_log",
        "linkage_verifier_result", "manual_crew", "manual_crew_member", "membership",
        "message", "message_geo", "message_observation", "mfa_challenge", "observation",
        "persona", "persona_event_log", "persona_membership", "personal_access_token",
        "profile", "reaction", "refresh_token", "source", "source_domain", "system_log",
        "system_user", "system_user_clearance_grant", "system_user_credential",
        "system_user_scope", "thread_summary",
    }
)
_AUDIT_AT_BASELINE = frozenset(
    {
        "audit_log", "file_access_acknowledgment", "file_access_journal",
        "signing_key_challenge", "system_user_signing_pubkey_history",
    }
)


def upgrade(engine_name: str) -> None:
    globals()[f"upgrade_{engine_name}"]()


def downgrade(engine_name: str) -> None:
    globals()[f"downgrade_{engine_name}"]()


def upgrade_main() -> None:
    _apply_main_schema(op.get_bind(), _MAIN_AT_BASELINE)


def downgrade_main() -> None:
    _drop_main_schema(op.get_bind(), _MAIN_AT_BASELINE)


def upgrade_audit() -> None:
    _apply_audit_schema(op.get_bind(), _AUDIT_AT_BASELINE)


def downgrade_audit() -> None:
    _drop_audit_schema(op.get_bind(), _AUDIT_AT_BASELINE)
