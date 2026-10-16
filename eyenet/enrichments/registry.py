# SPDX-License-Identifier: AGPL-3.0-or-later
"""Autodiscovered registry of enrichment plugins.

:func:`discover` imports every module under ``builtins/`` (and ``remote/`` if
present) and registers each CONCRETE :class:`Enrichment` subclass by
``(src_type, name)``. Adding an enrichment is therefore just dropping a module
with a concrete subclass into one of those packages, no central edit.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import TYPE_CHECKING

from eyenet.enrichments.base import Enrichment

if TYPE_CHECKING:
    from types import ModuleType

REGISTRY: dict[tuple[str, str], Enrichment] = {}
_state = {"discovered": False}


def _import_submodules(package: ModuleType) -> None:
    for info in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
        importlib.import_module(info.name)


def _concrete_subclasses(root: type[Enrichment]) -> list[type[Enrichment]]:
    out: list[type[Enrichment]] = []
    for sub in root.__subclasses__():
        out.extend(_concrete_subclasses(sub))
        if not inspect.isabstract(sub):
            out.append(sub)
    return out


def discover(*, force: bool = False) -> None:
    """Idempotently import the plugin packages and register every concrete
    enrichment. Cheap on repeat calls (guarded by a module flag). Imports are
    local and deferred on purpose, so discovery is a runtime step, not an
    import-time side effect."""
    if _state["discovered"] and not force:
        return
    import eyenet.enrichments.builtins as builtins_pkg  # noqa: PLC0415
    import eyenet.enrichments.remote as remote_pkg  # noqa: PLC0415

    _import_submodules(builtins_pkg)
    _import_submodules(remote_pkg)
    # Enrichment is abstract, but _concrete_subclasses filters to instantiable ones.
    for cls in _concrete_subclasses(Enrichment):  # type: ignore[type-abstract]
        inst = cls()
        REGISTRY[(inst.src_type, inst.name)] = inst
    _state["discovered"] = True


def get_enrichment(src_type: str, name: str) -> Enrichment:
    """The enrichment for ``(src_type, name)``; ValueError if none is registered."""
    discover()
    enr = REGISTRY.get((src_type, name))
    if enr is None:
        raise ValueError(f"unknown enrichment {src_type!r}.{name!r}")
    return enr


def enrichments_for_src_type(src_type: str) -> list[Enrichment]:
    """Every enrichment registered for ``src_type`` (empty if the type is unknown)."""
    discover()
    return [e for (st, _name), e in REGISTRY.items() if st == src_type]


__all__ = ["REGISTRY", "discover", "enrichments_for_src_type", "get_enrichment"]
