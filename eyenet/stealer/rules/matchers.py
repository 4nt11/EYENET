"""Per-type matchers. Byte-parity with ``matchers.js``.

Each matcher returns a fields dict on match or None on no-match. Container
matchers (``match_folder``) return ``{}`` on match. RE2 for untrusted
regex (same max_mem cap as the browser engine); yaml.safe_load for YAML.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

import re2
import yaml

from eyenet.stealer.rules.types import (
    ContainerInput,
    ContentInput,
    DelimiterMatch,
    ExtractSpec,
    FolderMatch,
    JsonMatch,
    KeyvalueIniMatch,
    KeyvalueMatch,
    RegexMatch,
    TemplateMatch,
    YamlMatch,
)

_RE2_MAX_MEM = 8 * 1024 * 1024


# YAML 1.2 Core-schema loader. PyYAML's SafeLoader defaults to YAML 1.1,
# which treats `yes`/`no`/`on`/`off` as booleans. That breaks forensic
# correctness: a stealer log with `Country: NO` would become `Country=False`
# on the Python side while js-yaml (YAML 1.2) correctly keeps the string.
# Here we remove every implicit bool resolver and re-add only the 1.2
# Core pattern (true/True/TRUE/false/False/FALSE).
class _YAML12SafeLoader(yaml.SafeLoader):
    pass


_YAML12SafeLoader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for (tag, rx) in rs if tag != "tag:yaml.org,2002:bool"]
    for ch, rs in _YAML12SafeLoader.yaml_implicit_resolvers.items()
}
_YAML12SafeLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def _re2_compile(pattern: str, multiline: bool = False, dotall: bool = False):
    opts = re2.Options()
    opts.max_mem = _RE2_MAX_MEM
    opts.one_line = not multiline
    opts.dot_nl = dotall
    return re2.compile(pattern, options=opts)


# --------------------------------------------------------------------- #
#  L1 container                                                          #
# --------------------------------------------------------------------- #

def match_folder(m: FolderMatch, inp: ContainerInput) -> dict[str, Any] | None:
    paths = set(inp.paths)
    for r in m.get("requires", []):
        if not _has_path(paths, r):
            return None
    for f in m.get("forbids", []):
        if _has_path(paths, f):
            return None
    req = len(m.get("requires", []))
    opt = sum(1 for p in m.get("optional", []) if _has_path(paths, p))
    min_score = m.get("min_score", req)
    return {} if req + opt >= min_score else None


def _has_path(paths: set[str], p: str) -> bool:
    if p.endswith("/"):
        return any(x.startswith(p) for x in paths)
    return p in paths


# --------------------------------------------------------------------- #
#  L3 content                                                            #
# --------------------------------------------------------------------- #

def match_regex(
    m: RegexMatch, ex: ExtractSpec | None, inp: ContentInput,
) -> dict[str, Any] | None:
    try:
        re_c = _re2_compile(m["pattern"], m.get("multiline", False), m.get("dotall", False))
    except Exception:
        return None
    try:
        hit = re_c.search(inp.text)
    except Exception:
        return None
    if hit is None:
        return None
    groups = hit.groupdict()
    if not groups:
        return {}
    want = (ex or {}).get("fields") or list(groups.keys())
    return {k: groups[k] for k in want if groups.get(k) is not None}


def match_template(
    m: TemplateMatch, ex: ExtractSpec | None, inp: ContentInput,
) -> dict[str, Any] | None:
    holes: list[str] = []
    out: list[str] = []
    i = 0
    tpl = m["template"]
    while i < len(tpl):
        if tpl[i] == "{":
            j = tpl.index("}", i)
            name = tpl[i + 1 : j]
            holes.append(name)
            out.append(f"(?P<{name}>.*?)")
            i = j + 1
        else:
            j = tpl.find("{", i)
            if j == -1:
                j = len(tpl)
            out.append(re2.escape(tpl[i:j]))
            i = j
    pattern = "^" + "".join(out) + "$"
    return match_regex(
        {"type": "regex", "pattern": pattern, "multiline": m.get("multiline", False), "dotall": True},
        ex or {"fields": holes},
        inp,
    )


def match_delimiter(
    m: DelimiterMatch, ex: ExtractSpec | None, inp: ContentInput,
) -> dict[str, Any] | None:
    cols = (ex or {}).get("columns") or {}
    first: dict[str, str] | None = None
    sep = m["separator"]
    for line in inp.text.splitlines():
        if m.get("skip_blank", True) and line.strip() == "":
            continue
        skip_comment = m.get("skip_comment_prefix")
        if skip_comment and line.startswith(skip_comment):
            continue
        parts = line.split(sep)
        if m.get("min_columns") and len(parts) < m["min_columns"]:
            continue
        row: dict[str, str] = {}
        for idx, field in cols.items():
            i = int(idx)
            if i < len(parts):
                row[field] = parts[i]
        if first is None:
            first = row
    return first


def match_json(
    m: JsonMatch, ex: ExtractSpec | None, inp: ContentInput,
) -> dict[str, Any] | None:
    try:
        doc = json.loads(inp.text)
    except json.JSONDecodeError:
        return None
    if not isinstance(doc, dict):
        return None
    for k in m.get("requires_keys", []):
        if k not in doc:
            return None
    return _extract_paths(doc, (ex or {}).get("paths") or {})


def match_yaml(
    m: YamlMatch, ex: ExtractSpec | None, inp: ContentInput,
) -> dict[str, Any] | None:
    try:
        # YAML 1.2 Core schema (see _YAML12SafeLoader above): `yes`/`no`/`on`/`off`
        # stay as strings to match js-yaml and preserve forensic correctness.
        doc = yaml.load(inp.text, Loader=_YAML12SafeLoader)
    except yaml.YAMLError:
        return None
    if not isinstance(doc, dict):
        return None
    for k in m.get("requires_keys", []):
        if k not in doc:
            return None
    return _extract_paths(doc, (ex or {}).get("paths") or {})


def match_keyvalue(
    m: KeyvalueMatch, ex: ExtractSpec | None, inp: ContentInput,
) -> dict[str, Any] | None:
    sep = m["separator"]
    strip = m.get("strip_whitespace", True)
    kv: dict[str, str] = {}
    for line in inp.text.splitlines():
        i = line.find(sep)
        if i <= 0:
            continue
        k = line[:i]
        v = line[i + len(sep) :]
        if strip:
            k = k.strip()
            v = v.strip()
        if k:
            kv[k.lower()] = v
    for k in m.get("requires_keys", []):
        if k.lower() not in kv:
            return None
    out: dict[str, str] = {}
    for src, dst in ((ex or {}).get("keys") or {}).items():
        v = kv.get(src.lower())
        if v is not None:
            out[dst] = v
    return out


def match_keyvalue_ini(
    m: KeyvalueIniMatch, ex: ExtractSpec | None, inp: ContentInput,
) -> dict[str, Any] | None:
    sections: dict[str, dict[str, str]] = {}
    cur = ""
    for raw in inp.text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            cur = line[1:-1]
            sections.setdefault(cur, {})
            continue
        i = line.find("=")
        if i <= 0:
            continue
        k = line[:i].strip()
        v = line[i + 1 :].strip()
        sections.setdefault(cur, {})[k] = v
    for s in m.get("requires_sections", []):
        if s not in sections:
            return None
    out: dict[str, str] = {}
    for dotted, dst in ((ex or {}).get("keys") or {}).items():
        dot = dotted.find(".")
        if dot <= 0:
            continue
        sec = dotted[:dot]
        key = dotted[dot + 1 :]
        v = sections.get(sec, {}).get(key)
        if v is not None:
            out[dst] = v
    return out


# --------------------------------------------------------------------- #
#  JSONPath-lite: $.a.b[0].c                                             #
# --------------------------------------------------------------------- #

_PATH_TOKEN = re2.compile(r"\.(\w+)|\[(\d+)\]")


def _extract_paths(doc: Any, paths: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field, expr in paths.items():
        v = _eval_path(doc, expr)
        # Drop missing, null, and non-finite floats (Infinity/NaN). In a
        # forensic context an extracted null means "no observation", not
        # "observation of null"; non-finite floats would crash json.dumps
        # on this side while JS would stringify them to "null" (divergence).
        if v is None:
            continue
        if isinstance(v, float) and not math.isfinite(v):
            continue
        # Parity with JS: JS has only float64. A YAML `foo: 1.0` round-trips
        # to the number 1, which stringifies to "1". Python's float stays
        # 1.0 and stringifies to "1.0". Coerce integer-valued floats to int
        # here so both engines emit the same thing. True fractional floats
        # (1.5) are untouched.
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        # Parity with JS: typeof bool is neither string nor number, so booleans
        # take the JSON-stringify branch. isinstance(True, int) is True in Python,
        # so the bool guard MUST precede the int check.
        if isinstance(v, bool):
            out[field] = json.dumps(v)  # "true" / "false"
        elif isinstance(v, (str, int, float)):
            out[field] = v
        else:
            out[field] = json.dumps(v, separators=(",", ":"))
    return out


def _eval_path(doc: Any, expr: str) -> Any:
    if not expr.startswith("$"):
        return None
    cur = doc
    for tok in _PATH_TOKEN.finditer(expr[1:]):
        if cur is None:
            return None
        key, idx = tok.group(1), tok.group(2)
        if key is not None:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(key)
        else:
            if not isinstance(cur, list):
                return None
            i = int(idx)
            cur = cur[i] if i < len(cur) else None
    return cur
