"""Per-type matchers. Byte-parity with ``matchers.js``.

Each matcher returns a fields dict on match or None on no-match. Container
matchers (``match_folder``) return ``{}`` on match. RE2 for untrusted
regex (same max_mem cap as the browser engine); yaml.safe_load for YAML.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Iterator
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
    # Note: google-re2's Options.one_line / Options.dot_nl are not honored
    # by the Python binding in a way that affects ^/$/. matching. Embedded
    # flags (?m) and (?s) are RE2's documented path and work both here and
    # on the browser side (@adguard/re2-wasm uses the standard m/s flags).
    opts = re2.Options()
    opts.max_mem = _RE2_MAX_MEM
    prefix = ""
    if multiline:
        prefix += "(?m)"
    if dotall:
        prefix += "(?s)"
    return re2.compile(prefix + pattern, options=opts)


# --------------------------------------------------------------------- #
#  L1 container                                                          #
# --------------------------------------------------------------------- #

def match_folder(m: FolderMatch, inp: ContainerInput) -> dict[str, Any] | None:
    """Folder matcher.

    Two authoring styles live side by side. If ``predicate`` is set, the
    engine walks that expression tree. Otherwise it lowers the flat
    ``requires`` / ``forbids`` / ``optional`` / ``min_score`` fields to
    an equivalent tree first (for one evaluation code path). The lowering
    is pure sugar: all legacy rules keep working byte-for-byte.
    """
    paths = set(inp.paths)
    paths_list = list(inp.paths)
    pred = m.get("predicate")
    if pred is None:
        pred = _lower_legacy_folder(m)
    try:
        if _eval_predicate(pred, paths, paths_list):
            return {}
    except _BadPredicate as exc:
        import logging
        logging.getLogger(__name__).warning("folder predicate rejected: %s", exc)
        return None
    return None


def _has_path(paths: set[str], p: str) -> bool:
    if p.endswith("/"):
        return any(x.startswith(p) for x in paths)
    return p in paths


class _BadPredicate(ValueError):
    """Load-time predicate shape error. Caught by the matcher and surfaced
    as a non-match + WARN so a broken rule can't take the pipeline down."""


def _eval_predicate(node: Any, paths: set[str], paths_list: list[str]) -> bool:
    """Walk a predicate tree. Each node is a dict with exactly one key
    naming the operator. Returns a bool.

    Operators: and / or / xor / not / at_least / exactly / at_most
    Leaves:    path / glob
    """
    if not isinstance(node, dict) or len(node) != 1:
        raise _BadPredicate(f"predicate node must be a single-key dict: {node!r}")
    op, body = next(iter(node.items()))
    if op == "and":
        if not isinstance(body, list):
            raise _BadPredicate("'and' expects a list")
        return all(_eval_predicate(c, paths, paths_list) for c in body)
    if op == "or":
        if not isinstance(body, list):
            raise _BadPredicate("'or' expects a list")
        return any(_eval_predicate(c, paths, paths_list) for c in body)
    if op == "xor":
        if not isinstance(body, list):
            raise _BadPredicate("'xor' expects a list")
        # Odd-parity semantics; matches standard digital logic.
        return sum(1 for c in body if _eval_predicate(c, paths, paths_list)) % 2 == 1
    if op == "not":
        return not _eval_predicate(body, paths, paths_list)
    if op in ("at_least", "exactly", "at_most"):
        if not isinstance(body, dict) or "of" not in body:
            raise _BadPredicate(f"{op!r} expects {{count, of: [...]}}")
        count = body.get("count", 0)
        if not isinstance(count, int) or count < 0:
            raise _BadPredicate(f"{op!r} count must be a non-negative integer")
        children = body["of"]
        if not isinstance(children, list):
            raise _BadPredicate(f"{op!r} 'of' must be a list")
        hits = sum(1 for c in children if _eval_predicate(c, paths, paths_list))
        if op == "at_least":
            return hits >= count
        if op == "at_most":
            return hits <= count
        return hits == count
    if op == "path":
        if not isinstance(body, str):
            raise _BadPredicate("'path' expects a string")
        return _has_path(paths, body)
    if op == "glob":
        if not isinstance(body, str):
            raise _BadPredicate("'glob' expects a string")
        from eyenet.stealer.rules.engine import match_glob  # local import to break cycle
        return any(match_glob(body, p) for p in paths_list)
    raise _BadPredicate(f"unknown predicate operator: {op!r}")


def _lower_legacy_folder(m: dict[str, Any]) -> dict[str, Any]:
    """Sugar: translate the flat requires/forbids/optional/min_score shape
    to an equivalent predicate tree. Keeps all pre-v2 rules working with
    no edits to the rules on disk.
    """
    requires = m.get("requires") or []
    forbids = m.get("forbids") or []
    optional = m.get("optional") or []
    min_score = m.get("min_score", len(requires))

    clauses: list[dict[str, Any]] = []
    for r in requires:
        clauses.append({"path": r})
    for f in forbids:
        clauses.append({"not": {"path": f}})
    if min_score > 0 and (requires or optional):
        clauses.append({
            "at_least": {
                "count": min_score,
                "of": [{"path": p} for p in requires + optional],
            }
        })
    if not clauses:
        return {"and": []}  # vacuously true
    return {"and": clauses}


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


def match_vdf(
    m: dict[str, Any], ex: ExtractSpec | None, inp: ContentInput,
) -> dict[str, Any] | None:
    """Valve Data Format (Steam's .vdf). Parse the KeyValues tree, honour
    requires_keys on the top level, extract via the standard JSONPath-lite
    paths. When ``pivot`` is set, bulkParse iterates each child of the
    pivot path as its own record (each record's $key sigil resolves to
    the child's dict key); match_vdf itself returns the first record so
    the primary-match path stays symmetric with keyvalue/json/yaml.
    """
    try:
        doc = _parse_vdf(inp.text)
    except _VDFParseError:
        return None
    if not isinstance(doc, dict):
        return None
    for k in m.get("requires_keys", []):
        if k not in doc:
            return None
    pivot = m.get("pivot")
    if pivot:
        # Primary-match: emit the FIRST child under the pivot so callers
        # that only use the single matcher still see a record. bulkParse
        # walks every child.
        for key, value in _pivot_children(doc, pivot):
            return _extract_vdf_record(value, key, (ex or {}).get("paths") or {})
        return None
    return extract_paths_vdf(doc, (ex or {}).get("paths") or {})


def iter_vdf(
    m: dict[str, Any], ex: ExtractSpec | None, text: str,
) -> Iterator[dict[str, Any]]:
    """Walk every pivot child as a record. Used by engine.bulk_parse."""
    try:
        doc = _parse_vdf(text)
    except _VDFParseError:
        return
    if not isinstance(doc, dict):
        return
    for k in m.get("requires_keys", []):
        if k not in doc:
            return
    pivot = m.get("pivot")
    if not pivot:
        yield extract_paths_vdf(doc, (ex or {}).get("paths") or {})
        return
    paths = (ex or {}).get("paths") or {}
    for key, value in _pivot_children(doc, pivot):
        yield _extract_vdf_record(value, key, paths)


def _pivot_children(doc: Any, pivot_expr: str):
    """Walk pivot_expr via JSONPath-lite and yield (child_key, child_value)
    pairs for each entry in the resolved map. Non-map pivots and missing
    pivots yield nothing."""
    cur = doc
    if not pivot_expr.startswith("$"):
        return
    for tok in _PATH_TOKEN.finditer(pivot_expr[1:]):
        if not isinstance(cur, dict):
            return
        key, _ = tok.group(1), tok.group(2)
        if key is None:
            return
        cur = cur.get(key)
        if cur is None:
            return
    if isinstance(cur, dict):
        yield from cur.items()


def _extract_vdf_record(value: Any, key_name: str, paths: dict[str, str]) -> dict[str, Any]:
    """Extract fields from one pivot child. The $key sigil resolves to the
    child's dict key (e.g. the SteamID in loginusers.vdf). All other
    paths navigate through the child's value via JSONPath-lite."""
    out: dict[str, Any] = {}
    for field, expr in paths.items():
        if expr == "$key":
            out[field] = key_name
            continue
        v = _eval_path(value, expr)
        if v is None:
            continue
        if isinstance(v, str):
            out[field] = v
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            out[field] = v
        else:
            out[field] = json.dumps(v, separators=(",", ":"))
    return out


def extract_paths_vdf(doc: Any, paths: dict[str, str]) -> dict[str, Any]:
    """Same output shape as _extract_paths for JSON/YAML, kept separate so
    the VDF parser's native dict (always str-valued leaves) doesn't trip
    the whole-number-float / bool-stringify paths that only apply to
    JSON-ish types."""
    out: dict[str, Any] = {}
    for field, expr in paths.items():
        v = _eval_path(doc, expr)
        if v is None:
            continue
        if isinstance(v, str):
            out[field] = v
        else:
            out[field] = json.dumps(v, separators=(",", ":"))
    return out


# --- VDF parser --- #
# KeyValues format: alternating "key" + ("value" | { nested }) pairs.
# Quoted strings support \" \\ \n \t escapes. '//' comments run to EOL.
# No arrays; dicts can have duplicate keys in the wild (last-wins when
# we flatten into a Python dict; matches game behaviour).

class _VDFParseError(ValueError):
    pass


def _parse_vdf(text: str) -> dict[str, Any]:
    p = _VDFParser(text)
    return p.parse_root()


class _VDFParser:
    __slots__ = ("text", "i", "n")

    def __init__(self, text: str) -> None:
        self.text = text
        self.i = 0
        self.n = len(text)

    def parse_root(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        while True:
            self._skip()
            if self.i >= self.n:
                break
            key = self._read_string()
            self._skip()
            if self.i >= self.n:
                raise _VDFParseError(f"dangling key {key!r} at eof")
            if self.text[self.i] == "{":
                self.i += 1
                out[key] = self._read_object()
            else:
                out[key] = self._read_string()
        return out

    def _read_object(self) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        while True:
            self._skip()
            if self.i >= self.n:
                raise _VDFParseError("unterminated object")
            ch = self.text[self.i]
            if ch == "}":
                self.i += 1
                return obj
            key = self._read_string()
            self._skip()
            if self.i >= self.n:
                raise _VDFParseError(f"dangling key {key!r} inside object")
            if self.text[self.i] == "{":
                self.i += 1
                obj[key] = self._read_object()
            else:
                obj[key] = self._read_string()

    def _read_string(self) -> str:
        if self.i >= self.n:
            raise _VDFParseError("expected string at eof")
        if self.text[self.i] == '"':
            self.i += 1
            start = self.i
            buf: list[str] = []
            while self.i < self.n:
                ch = self.text[self.i]
                if ch == "\\" and self.i + 1 < self.n:
                    nxt = self.text[self.i + 1]
                    if nxt == "n":
                        buf.append("\n")
                    elif nxt == "t":
                        buf.append("\t")
                    elif nxt == "r":
                        buf.append("\r")
                    elif nxt == '"':
                        buf.append('"')
                    elif nxt == "\\":
                        buf.append("\\")
                    else:
                        buf.append(nxt)
                    self.i += 2
                    continue
                if ch == '"':
                    self.i += 1
                    return "".join(buf) if buf else self.text[start:self.i - 1]
                buf.append(ch)
                self.i += 1
            raise _VDFParseError("unterminated quoted string")
        # Unquoted bareword: read until whitespace or control.
        start = self.i
        while self.i < self.n and self.text[self.i] not in ' \t\r\n{}"':
            self.i += 1
        if self.i == start:
            raise _VDFParseError(f"expected string at offset {self.i}")
        return self.text[start:self.i]

    def _skip(self) -> None:
        while self.i < self.n:
            ch = self.text[self.i]
            if ch in " \t\r\n":
                self.i += 1
                continue
            if ch == "/" and self.i + 1 < self.n and self.text[self.i + 1] == "/":
                while self.i < self.n and self.text[self.i] != "\n":
                    self.i += 1
                continue
            return


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
