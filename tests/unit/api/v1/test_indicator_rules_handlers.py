# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the indicator-rule CRUD handlers (Phase 4).

Bypasses ASGI routing (coverage can't trace it); scope enforcement via
RequireScope is ASGI-level. Exercises the handler logic + write-time validation.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from eyenet.api.deps import ConflictError, ResourceNotFound
from eyenet.api.v1.indicators.api_create_indicator_rule import indicator_rules_create
from eyenet.api.v1.indicators.api_delete_indicator_rule import indicator_rules_delete
from eyenet.api.v1.indicators.api_list_indicator_rules import indicator_rules_list
from eyenet.api.v1.indicators.api_update_indicator_rule import indicator_rules_update
from eyenet.api.v1.schemas.indicators import (
    IndicatorRuleCreate,
    IndicatorRuleUpdate,
)
from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.linker.indicator_rules import VENDORED_INDICATOR_RULES
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

pytestmark = pytest.mark.unit


@pytest.fixture
def audit(storage: BaseRepository) -> AuditEmitter:
    return AuditEmitter(
        BusEnvelopePublisher(MemoryBus()), storage, service="test", instance_id="t0"
    )


async def test_list_returns_vendored_catalog(storage: BaseRepository, mkuser) -> None:
    rows = await indicator_rules_list(mkuser("read:collectors"), storage)
    assert len(rows) == len(VENDORED_INDICATOR_RULES)
    assert all(r.vendored for r in rows)


async def test_create_custom_rule(storage: BaseRepository, mkuser, audit: AuditEmitter) -> None:
    body = IndicatorRuleCreate(kind="email", pattern=r"\btest@custom\.rule\b")
    row = await indicator_rules_create(body, mkuser("write:collectors"), storage, audit)
    assert row.vendored is False
    assert row.kind == "email"
    rows = await indicator_rules_list(mkuser("read:collectors"), storage)
    assert len(rows) == len(VENDORED_INDICATOR_RULES) + 1


def test_create_accepts_custom_slug_kind() -> None:
    # Kinds are OPEN now: a custom slug outside InfrastructureKind is valid.
    assert IndicatorRuleCreate(kind="ipv4", pattern=r"\bx\b").kind == "ipv4"


def test_create_rejects_non_slug_kind() -> None:
    # Still constrained to a clean lowercase slug so the search facet stays tidy.
    for bad in ("Not A Kind", "UPPER", "has space", "sym!bol", "1leading"):
        with pytest.raises(ValidationError):
            IndicatorRuleCreate(kind=bad, pattern=r"\bx\b")


def test_create_rejects_lookbehind_pattern() -> None:
    with pytest.raises(ValidationError):
        IndicatorRuleCreate(kind="email", pattern=r"(?<!x)@y")


async def test_create_duplicate_raises_integrity(
    storage: BaseRepository, mkuser, audit: AuditEmitter
) -> None:
    body = IndicatorRuleCreate(kind="tox", pattern=r"\bcustomdup\b")
    await indicator_rules_create(body, mkuser("write:collectors"), storage, audit)
    with pytest.raises(IntegrityError):
        await indicator_rules_create(body, mkuser("write:collectors"), storage, audit)


async def test_patch_disables_vendored_rule(
    storage: BaseRepository, mkuser, audit: AuditEmitter
) -> None:
    target = (await indicator_rules_list(mkuser("read:collectors"), storage))[0]
    updated = await indicator_rules_update(
        target.id,
        IndicatorRuleUpdate(enabled=False),
        mkuser("write:collectors"),
        storage,
        audit,
    )
    assert updated.enabled is False
    assert updated.vendored is True  # vendored rule, disabled (survives re-seed)


async def test_patch_missing_raises_not_found(
    storage: BaseRepository, mkuser, audit: AuditEmitter
) -> None:
    from uuid import uuid4

    with pytest.raises(ResourceNotFound):
        await indicator_rules_update(
            uuid4(),
            IndicatorRuleUpdate(enabled=False),
            mkuser("write:collectors"),
            storage,
            audit,
        )


async def test_delete_custom_ok_vendored_blocked(
    storage: BaseRepository, mkuser, audit: AuditEmitter
) -> None:
    # custom rule deletes cleanly
    created = await indicator_rules_create(
        IndicatorRuleCreate(kind="email", pattern=r"\bgone@now\.x\b"),
        mkuser("write:collectors"),
        storage,
        audit,
    )
    await indicator_rules_delete(created.id, mkuser("admin:collectors"), storage, audit)
    assert await storage.get_indicator_rule(created.id) is None

    # vendored rule cannot be deleted
    vendored = (await indicator_rules_list(mkuser("read:collectors"), storage))[0]
    with pytest.raises(ConflictError):
        await indicator_rules_delete(vendored.id, mkuser("admin:collectors"), storage, audit)
    assert await storage.get_indicator_rule(vendored.id) is not None


async def test_delete_missing_raises_not_found(
    storage: BaseRepository, mkuser, audit: AuditEmitter
) -> None:
    from uuid import uuid4

    with pytest.raises(ResourceNotFound):
        await indicator_rules_delete(uuid4(), mkuser("admin:collectors"), storage, audit)
