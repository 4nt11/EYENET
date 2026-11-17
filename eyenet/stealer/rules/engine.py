"""Engine orchestrator. Byte-parity with ``engine.js``.

Inputs are pre-validated dicts (JSON Schema at load) + a VictimFolder.
No I/O. No logging. Pure functions. Thread-safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import re2

from eyenet.stealer.rules.matchers import _re2_compile  # noqa: F401 - shared RE2 config
from eyenet.stealer.rules.matchers import (
    match_delimiter,
    match_folder,
    match_json,
    iter_vdf,
    iter_xml,
    match_keyvalue,
    match_keyvalue_ini,
    match_vdf,
    match_xml,
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
        # Optional opt-in family filter. Used by fallback rules (e.g. the
        # combolist probes) that must not fire inside a real stealer folder.
        req_fam = r.get("requires_container_family")
        if req_fam is not None and req_fam != family:
            continue
        glob = r.get("path_glob", "**/*")
        for file in folder.files:
            if not match_glob(glob, file.path):
                continue
            ev = _eval_content(r, file)
            ev.file_path = file.path
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
    rej = _rule_rejects(r, mapped)
    if rej is not None:
        return EvalResult(**base, matched=False, reason=f"reject: {rej}")
    normed = apply_normalize(mapped, r["normalize"]) if r.get("normalize") else mapped
    return EvalResult(**base, matched=True, fields=_escape_nulls(normed))


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
    elif kind == "vdf":
        fields = match_vdf(m, ex, file)  # type: ignore[arg-type]
    elif kind == "xml":
        fields = match_xml(m, ex, file)  # type: ignore[arg-type]
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
    rej = _rule_rejects(r, mapped)
    if rej is not None:
        return EvalResult(**base, matched=False, reason=f"reject: {rej}")
    normed = apply_normalize(mapped, r["normalize"]) if r.get("normalize") else mapped
    return EvalResult(**base, matched=True, fields=_escape_nulls(normed))


def _rule_rejects(r: RuleSpec, fields: dict[str, Any]) -> str | None:
    """Return the first reject_pattern that matches any extracted field value,
    or None if nothing rejects. Patterns are RE2 (ReDoS-safe, max_mem bounded).
    Applied AFTER map and BEFORE normalize so raw banner/null-sentinel text is
    caught before any transform masks it (e.g. uppercase("none") would still
    catch 'NONE' but a truncated value could evade a literal-equality rule).
    Mirrors ulpextract's bannerLogin + isNullPassword behavior at the DSL layer.
    """
    patterns = r.get("reject_patterns") or []
    if not patterns:
        return None
    try:
        compiled = [_re2_compile(p) for p in patterns]
    except Exception:
        return None  # bad pattern = no reject (fail-open; validation runs at load)
    for v in fields.values():
        s = str(v)
        for raw, re_c in zip(patterns, compiled, strict=True):
            try:
                if re_c.search(s):
                    return raw
            except Exception:
                continue
    return None


def _escape_nulls(fields: dict[str, Any]) -> dict[str, Any]:
    """Replace raw NUL (U+0000) in string values with the literal 4-char
    escape ``\\x00``. Lossless: round-trips, stays searchable, surfaces the
    attack to the analyst instead of hiding it. Applied after normalize so
    truncate operates on the original byte length, not the escaped form.
    Nested-object values arrived as JSON blobs where json.dumps already
    encoded any inner null as ``\\u0000``, so the raw-NUL check won't fire
    on them; parity with JS is preserved.
    """
    out: dict[str, Any] = {}
    for k, v in fields.items():
        out[k] = v.replace("\x00", "\\x00") if isinstance(v, str) and "\x00" in v else v
    return out


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
