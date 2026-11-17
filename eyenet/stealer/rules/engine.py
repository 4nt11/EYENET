"""Engine orchestrator. Byte-parity with ``engine.js``.

Inputs are pre-validated dicts (JSON Schema at load) + a VictimFolder.
No I/O. No logging. Pure functions. Thread-safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import re2

from eyenet.stealer.rules.matchers import (
    match_delimiter,
    match_folder,
    match_json,
    match_keyvalue,
    match_keyvalue_ini,
    match_regex,
    match_template,
    match_yaml,
)
from eyenet.stealer.rules.normalize import apply_normalize
from eyenet.stealer.rules.types import (
    ContainerInput,
    EvalResult,
    RuleSpec,
    VictimFolder,
)


@dataclass(slots=True)
class RunResult:
    family: str | None
    fields: dict[str, Any] = field(default_factory=dict)
    evaluations: list[EvalResult] = field(default_factory=list)


def run_rules(rules: list[RuleSpec], folder: VictimFolder) -> RunResult:
    evaluations: list[EvalResult] = []
    container_input = ContainerInput(paths=tuple(f.path for f in folder.files))

    # L1 container winner by priority.
    winner: EvalResult | None = None
    for r in rules:
        if r.get("layer") != "container":
            continue
        ev = _eval_container(r, container_input)
        evaluations.append(ev)
        if ev.matched and (winner is None or r["priority"] > winner.priority):
            winner = ev
    family = winner.family if winner else None

    # L3 content: ascending priority so later wins on key collision.
    content_rules = sorted(
        (r for r in rules if r.get("layer") == "content"),
        key=lambda r: r.get("priority", 0),
    )

    merged: dict[str, Any] = {}
    for r in content_rules:
        glob = r.get("path_glob", "**/*")
        for file in folder.files:
            if not match_glob(glob, file.path):
                continue
            ev = _eval_content(r, file)
            evaluations.append(ev)
            if ev.matched and ev.fields:
                merged.update(ev.fields)

    return RunResult(family=family, fields=merged, evaluations=evaluations)


def _eval_container(r: RuleSpec, inp: ContainerInput) -> EvalResult:
    base = _base_eval(r)
    m = r.get("match", {})
    if m.get("type") != "folder":
        return EvalResult(**base, matched=False, reason="container rule requires folder match")
    fields = match_folder(m, inp)  # type: ignore[arg-type]
    if fields is None:
        return EvalResult(**base, matched=False, reason="no match")
    mapped = _apply_map(fields, r.get("map"))
    normed = apply_normalize(mapped, r["normalize"]) if r.get("normalize") else mapped
    return EvalResult(**base, matched=True, fields=normed)


def _eval_content(r: RuleSpec, file) -> EvalResult:
    base = _base_eval(r)
    m = r.get("match", {})
    kind = m.get("type")
    ex = r.get("extract")
    if kind == "regex":
        fields = match_regex(m, ex, file)  # type: ignore[arg-type]
    elif kind == "template":
        fields = match_template(m, ex, file)  # type: ignore[arg-type]
    elif kind == "delimiter":
        fields = match_delimiter(m, ex, file)  # type: ignore[arg-type]
    elif kind == "json":
        fields = match_json(m, ex, file)  # type: ignore[arg-type]
    elif kind == "yaml":
        fields = match_yaml(m, ex, file)  # type: ignore[arg-type]
    elif kind == "keyvalue":
        fields = match_keyvalue(m, ex, file)  # type: ignore[arg-type]
    elif kind == "keyvalue_ini":
        fields = match_keyvalue_ini(m, ex, file)  # type: ignore[arg-type]
    elif kind == "folder":
        return EvalResult(**base, matched=False, reason="folder match only valid in container layer")
    else:
        return EvalResult(**base, matched=False, reason=f"unknown match type: {kind}")

    if fields is None:
        return EvalResult(**base, matched=False, reason="no match")
    mapped = _apply_map(fields, r.get("map"))
    normed = apply_normalize(mapped, r["normalize"]) if r.get("normalize") else mapped
    return EvalResult(**base, matched=True, fields=normed)


def _base_eval(r: RuleSpec) -> dict[str, Any]:
    return {
        "rule_id": r["id"],
        "layer": r["layer"],
        "family": r["family"],
        "priority": r.get("priority", 0),
    }


def _apply_map(fields: dict[str, Any], m) -> dict[str, Any]:
    if not m:
        return fields
    out: dict[str, Any] = {}
    drop = set(m.get("_drop", []))
    rename = m.get("rename", {})
    for k, v in fields.items():
        if k in drop:
            continue
        out[rename.get(k, k)] = v
    return out


def match_glob(glob: str, path: str) -> bool:
    """gitignore-style glob matching. Parity with JS matchGlob."""
    # Same substitution algorithm as the JS impl so the regex is identical.
    escaped = []
    for ch in glob:
        if ch in r".+^${}()|[]\\":
            escaped.append("\\" + ch)
        elif ch in "*?":
            escaped.append(ch)
        else:
            escaped.append(ch)
    pattern = "".join(escaped)
    pattern = pattern.replace("**", "\x00GLOBSTAR\x00")
    pattern = pattern.replace("*", "[^/]*")
    pattern = pattern.replace("?", "[^/]")
    pattern = pattern.replace("\x00GLOBSTAR\x00", ".*")
    return re2.match("^" + pattern + "$", path) is not None
