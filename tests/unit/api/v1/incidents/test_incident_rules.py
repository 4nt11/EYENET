# SPDX-License-Identifier: AGPL-3.0-or-later
"""incident-rule CRUD handlers — direct-call (validation, not-found, happy paths)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eyenet.api.deps import ConflictError, ResourceNotFound, UnprocessableError
from eyenet.api.v1.incidents.api_create_incident_rule import create_incident_rule
from eyenet.api.v1.incidents.api_delete_incident_rule import delete_incident_rule
from eyenet.api.v1.incidents.api_update_incident_rule import update_incident_rule
from eyenet.api.v1.schemas.incidents import IncidentRuleCreate, IncidentRuleUpdate

pytestmark = pytest.mark.unit

_USER = SimpleNamespace(username="op", user_id=uuid4())


class _FakeStore:
    def __init__(self) -> None:
        self.rules: dict = {}

    async def list_incident_rules(self, *, enabled_only: bool = False):
        vals = list(self.rules.values())
        return [r for r in vals if r.enabled] if enabled_only else vals

    async def create_incident_rule(self, row):
        self.rules[row.id] = row

    async def get_incident_rule(self, rule_id):
        return self.rules.get(rule_id)

    async def update_incident_rule(self, rule_id, fields):
        r = self.rules.get(rule_id)
        if r is None:
            return False
        for k, v in fields.items():
            setattr(r, k, v)
        return True

    async def delete_incident_rule(self, rule_id):
        return self.rules.pop(rule_id, None) is not None


def _create(store, **kw):
    body = IncidentRuleCreate(
        **{"name": "op_x", "pattern": r"\bmybooter\b", "label": "crimeware_tooling", **kw}
    )
    return asyncio.run(create_incident_rule(body=body, current_user=_USER, storage=store))


def test_create_happy_path() -> None:
    store = _FakeStore()
    out = _create(store)
    assert out.name == "op_x"
    assert out.label == "crimeware_tooling"
    assert out.created_by == "op"
    assert len(store.rules) == 1


def test_create_rejects_bad_pattern() -> None:
    with pytest.raises(UnprocessableError):
        _create(_FakeStore(), pattern="(((")


def test_create_rejects_bad_label() -> None:
    with pytest.raises(UnprocessableError):
        _create(_FakeStore(), label="not_a_head")


def test_create_rejects_builtin_name_collision() -> None:
    with pytest.raises(ConflictError):
        _create(_FakeStore(), name="tool_sale")  # a built-in signal name


def test_create_rejects_duplicate_name() -> None:
    store = _FakeStore()
    _create(store, name="dup")
    with pytest.raises(ConflictError):
        _create(store, name="dup")


def test_update_not_found() -> None:
    with pytest.raises(ResourceNotFound):
        asyncio.run(
            update_incident_rule(
                rule_id=uuid4(),
                body=IncidentRuleUpdate(enabled=False),
                _=_USER,
                storage=_FakeStore(),
            )
        )


def test_update_toggles_enabled() -> None:
    store = _FakeStore()
    created = _create(store, name="toggle")
    out = asyncio.run(
        update_incident_rule(
            rule_id=created.id, body=IncidentRuleUpdate(enabled=False), _=_USER, storage=store
        )
    )
    assert out.enabled is False


def test_update_rejects_bad_pattern() -> None:
    store = _FakeStore()
    created = _create(store, name="p")
    with pytest.raises(UnprocessableError):
        asyncio.run(
            update_incident_rule(
                rule_id=created.id, body=IncidentRuleUpdate(pattern="(("), _=_USER, storage=store
            )
        )


def test_delete_happy_and_not_found() -> None:
    store = _FakeStore()
    created = _create(store, name="del")
    asyncio.run(delete_incident_rule(rule_id=created.id, _=_USER, storage=store))
    assert store.rules == {}
    with pytest.raises(ResourceNotFound):
        asyncio.run(delete_incident_rule(rule_id=created.id, _=_USER, storage=store))
