# SPDX-License-Identifier: AGPL-3.0-or-later
"""Indicator ruleset seed — SQLite-impl probe.

Pins ``EYENET_STORAGE_TYPE=sqlite`` + ``_sqlite`` suffix because it inspects the
migration-seeded ruleset directly on the backend engine. The seed itself is
dialect-neutral (the same ``seed_indicator_rules`` runs in the Postgres 0007 and
SQLite 0010 revisions), so this guards its two load-bearing invariants:

  1. the full vendored catalog ships enabled;
  2. re-seeding is idempotent AND never rewrites ``enabled`` — an operator disable
     survives a later vendored-catalog upgrade (the Wazuh promise).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from eyenet.linker.indicator_rules import VENDORED_INDICATOR_RULES
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.storage.sqlite_repo.database import seed_indicator_rules

pytestmark = pytest.mark.unit


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> BaseRepository:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    return get_repository(in_memory=True)


def test_vendored_catalog_seeded_enabled(storage: BaseRepository) -> None:
    with storage.sync_engine.connect() as c:
        total = c.execute(text("SELECT COUNT(*) FROM indicator_rule")).scalar()
        vendored = c.execute(
            text("SELECT COUNT(*) FROM indicator_rule WHERE vendored AND enabled")
        ).scalar()
    assert total == len(VENDORED_INDICATOR_RULES)
    assert vendored == len(VENDORED_INDICATOR_RULES)


def test_reseed_is_idempotent_and_preserves_operator_disable(storage: BaseRepository) -> None:
    # Operator disables one vendored rule.
    with storage.sync_engine.begin() as c:
        c.execute(
            text("UPDATE indicator_rule SET enabled = 0 WHERE kind = :k"),
            {"k": "wallet_xmr"},
        )

    # A later vendored-catalog upgrade re-runs the seed.
    with storage.sync_engine.begin() as c:
        added = seed_indicator_rules(c)

    assert added == 0  # nothing duplicated
    with storage.sync_engine.connect() as c:
        total = c.execute(text("SELECT COUNT(*) FROM indicator_rule")).scalar()
        still_disabled = c.execute(
            text("SELECT enabled FROM indicator_rule WHERE kind = :k"),
            {"k": "wallet_xmr"},
        ).scalar()
    assert total == len(VENDORED_INDICATOR_RULES)
    assert not still_disabled  # the disable survived the re-seed
