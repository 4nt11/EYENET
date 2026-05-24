"""PLAN §4.2 — the build refuses if a Surface=db module exports a SUBJECT,
or if a Surface=bus / bus+db module fails to export one.

This test introspects every module under `eyenet.contracts` and applies the
classification table from PLAN §4.2.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import eyenet.contracts as contracts_pkg

# Classification per PLAN §4.2. Modules NOT listed here are interface-only
# (Surface=—) and must NOT export a SUBJECT either.
_BUS_MODULES: frozenset[str] = frozenset(
    {
        "eyenet.contracts.raw_message",
        "eyenet.contracts.observation",
        "eyenet.contracts.identity",
        "eyenet.contracts.attribution",
        "eyenet.contracts.audit",
    }
)
_DB_ONLY_MODULES: frozenset[str] = frozenset(
    {
        "eyenet.contracts.source",
        "eyenet.contracts.actor",
        "eyenet.contracts.group",
        "eyenet.contracts.message",
        "eyenet.contracts.social_graph",
        "eyenet.contracts.infrastructure",
        "eyenet.contracts.case",
        "eyenet.contracts.clearance",
        "eyenet.contracts.system_user",
        "eyenet.contracts.syslog",
        "eyenet.contracts.corpus",
        "eyenet.contracts.feedback",
    }
)
_INTERFACE_MODULES: frozenset[str] = frozenset(
    {
        "eyenet.contracts.audit_subjects",
        "eyenet.contracts.bus",
        "eyenet.contracts.storage",
        "eyenet.contracts.identity_pool",
        "eyenet.contracts.collector",
        "eyenet.contracts.sensor",
        "eyenet.contracts.enums",
        "eyenet.contracts._base",
        "eyenet.contracts",
    }
)


def _all_contract_modules() -> list[str]:
    return [
        f"eyenet.contracts.{info.name}" for info in pkgutil.iter_modules(contracts_pkg.__path__)
    ] + ["eyenet.contracts"]


@pytest.mark.contract
def test_classification_covers_every_module() -> None:
    found = set(_all_contract_modules())
    classified = _BUS_MODULES | _DB_ONLY_MODULES | _INTERFACE_MODULES
    missing = found - classified
    extra = classified - found
    assert not missing, f"unclassified contract modules: {sorted(missing)}"
    assert not extra, f"classified non-existent modules: {sorted(extra)}"


@pytest.mark.contract
def test_db_only_modules_export_no_subject() -> None:
    for name in _DB_ONLY_MODULES:
        mod = importlib.import_module(name)
        for attr in ("SUBJECT", "SUBJECT_PREFIX", "subject", "subject_for"):
            assert not hasattr(mod, attr), (
                f"{name} is Surface=db but exports {attr!r} — "
                "PLAN §4.2 forbids this. Move it or reclassify the module."
            )


@pytest.mark.contract
def test_bus_modules_export_at_least_one_subject() -> None:
    for name in _BUS_MODULES:
        mod = importlib.import_module(name)
        subject_attrs = [a for a in dir(mod) if a == "SUBJECT" or a.startswith("SUBJECT_")]
        assert subject_attrs, f"{name} is Surface=bus/bus+db but exports no SUBJECT* constant"


@pytest.mark.contract
def test_interface_modules_export_no_subject() -> None:
    for name in _INTERFACE_MODULES:
        mod = importlib.import_module(name)
        for attr in ("SUBJECT", "SUBJECT_PREFIX"):
            assert not hasattr(mod, attr), f"{name} is interface-only but exports {attr!r}"
