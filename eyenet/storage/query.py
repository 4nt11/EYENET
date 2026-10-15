# SPDX-License-Identifier: AGPL-3.0-or-later
"""Neutral search query language — parser + field registry (GLOBAL_SEARCH.md §9).

Because EYENET ships two storage backends (SQLite FTS5, future Postgres tsvector)
whose native query grammars differ, we do NOT forward raw engine syntax. We own ONE
grammar, parse operator input to a backend-neutral AST here, and each backend's
``SearchMixin`` compiles that AST to parameterized SQL. This module is pure — it
never touches SQL — so the grammar + the field whitelist (the security boundary)
can be exhaustively unit/fuzz tested in isolation.

Grammar (§9.2)::

    or_expr   := and_expr (OR and_expr)*
    and_expr  := factor (AND? factor)*     # adjacency = implicit AND
    factor    := NOT? ( '(' or_expr ')' | predicate | term )
    predicate := FIELD ( '==' | '!=' | '=~' | ':' ) value
    term      := WORD | '"' PHRASE '"' | WORD '*'

``=~`` is the LIKE (case-insensitive substring) operator. ``&&`` / ``||`` are
accepted as C-style aliases for ``AND`` / ``OR``. Field names are
whitelisted via :data:`FIELD_REGISTRY`; an unknown field raises
:class:`UnknownFieldError` (the API turns it into a clean 422). Values are NEVER
interpolated — the compiler always binds them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ── AST ──────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Term:
    """A text-plane term: a bare word, a ``"quoted phrase"``, or a ``prefix*``."""

    text: str
    phrase: bool = False
    prefix: bool = False


@dataclass(frozen=True)
class Field:
    """A field-plane predicate: ``field OP value`` (op ∈ ==, !=, =~, :)."""

    field: str
    op: str
    value: str


@dataclass(frozen=True)
class Not:
    child: Node


@dataclass(frozen=True)
class And:
    children: tuple[Node, ...]


@dataclass(frozen=True)
class Or:
    children: tuple[Node, ...]


Node = Term | Field | Not | And | Or
OPERATORS = ("==", "!=", "=~", ":")


# ── Field registry (the whitelist + security boundary, §9.3) ──────────────────
@dataclass(frozen=True)
class FieldSpec:
    """Where a dotted field resolves in ``search_document`` and how it matches.

    ``target`` is one of: a real column (``title``/``status``/``handles``/
    ``subtitle``/``haystack``), or ``fields.<key>`` for the structured JSON bag.
    ``kind`` is ``text`` (FTS-ranked via ``:``) or ``exact`` (filter). Using a
    field implicitly scopes results to ``entity_type``.
    """

    entity_type: str
    target: str
    kind: str


FIELD_REGISTRY: dict[str, FieldSpec] = {
    "message.content": FieldSpec("message", "haystack", "text"),
    "message.author": FieldSpec("message", "fields.author", "exact"),
    "group.title": FieldSpec("group", "title", "text"),
    "group.status": FieldSpec("group", "status", "exact"),
    "forum.thread.author": FieldSpec("thread", "fields.thread_author", "exact"),
    "actor.handle": FieldSpec("actor", "handles", "exact"),
    "artifact.value": FieldSpec("artifact", "title", "text"),
    "artifact.kind": FieldSpec("artifact", "kind", "exact"),
    "case.title": FieldSpec("case", "title", "text"),
    "document.text": FieldSpec("document", "haystack", "text"),
}


class UnknownFieldError(ValueError):
    """A dotted field that is not in the registry (→ 422, never a silent empty set)."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"unknown search field '{field}'; known fields: {sorted(FIELD_REGISTRY)}")


class QueryParseError(ValueError):
    """Unparseable query — the caller degrades to a best-effort text search (§9.4)."""


# ── Tokenizer ─────────────────────────────────────────────────────────────────
# A word is a run of non-delimiter chars; ``:`` splits as an operator UNLESS it is
# part of a scheme ("://"), so URLs stay whole. ``=``/``!``/``&``/``|`` never appear
# in words, so ``==``/``!=``/``=~`` and the ``&&``/``||`` C-style boolean aliases
# always split out even when glued (``field==value``, ``a&&b``).
_TOKEN_RE = re.compile(
    r"""
      \s+
    | (?P<lp>\()
    | (?P<rp>\))
    | (?P<phrase>"[^"]*")
    | (?P<booland>&&)
    | (?P<boolor>\|\|)
    | (?P<op>==|!=|=~|:(?!/))
    | (?P<word>(?:[^\s()"=!:&|]|:(?=/))+)
    """,
    re.VERBOSE,
)

_KEYWORDS = {"and": "AND", "or": "OR", "not": "NOT"}
#: A dotted field path (``message.author``, ``forum.thread.author``). Used only to tell
#: a field-predicate ATTEMPT from a plain term; the registry is the real whitelist.
_FIELD_PATH = re.compile(r"[A-Za-z][\w-]*(?:\.[A-Za-z][\w-]*)+")


def _tokenize(text: str) -> list[tuple[str, str]]:
    toks: list[tuple[str, str]] = []
    for m in _TOKEN_RE.finditer(text):
        kind = m.lastgroup
        if kind is None:  # whitespace
            continue
        val = m.group()
        if kind == "word":
            kw = _KEYWORDS.get(val.lower())
            toks.append((kw, val) if kw else ("word", val))
        elif kind == "phrase":
            toks.append(("phrase", val[1:-1]))  # strip the quotes
        elif kind == "lp":
            toks.append(("lp", val))
        elif kind == "rp":
            toks.append(("rp", val))
        elif kind == "op":
            toks.append(("op", val))
        elif kind == "booland":  # && is an alias for AND
            toks.append(("AND", val))
        elif kind == "boolor":  # || is an alias for OR
            toks.append(("OR", val))
    return toks


# ── Recursive-descent parser ──────────────────────────────────────────────────
def _is_empty(n: Node) -> bool:
    return isinstance(n, Term) and n.text == "" and not n.phrase


def _combine(kind: type[And] | type[Or], nodes: list[Node]) -> Node:
    """Build an And/Or, dropping empty terms (from dangling operators / stray parens)."""
    real = [n for n in nodes if not _is_empty(n)]
    if not real:
        return Term("")
    if len(real) == 1:
        return real[0]
    return kind(tuple(real))


class _Parser:
    def __init__(self, toks: list[tuple[str, str]]) -> None:
        self._t = toks
        self._i = 0

    def _peek(self) -> tuple[str, str] | None:
        return self._t[self._i] if self._i < len(self._t) else None

    def _next(self) -> tuple[str, str]:
        tok = self._t[self._i]
        self._i += 1
        return tok

    def parse(self) -> Node | None:
        if not self._t:
            return None
        node = self._or()
        return None if _is_empty(node) else node

    def _or(self) -> Node:
        nodes = [self._and()]
        while (p := self._peek()) and p[0] == "OR":
            self._next()
            nodes.append(self._and())
        return _combine(Or, nodes)

    def _and(self) -> Node:
        nodes = [self._factor()]
        while (p := self._peek()) and p[0] not in ("OR", "rp"):
            if p[0] == "AND":
                self._next()  # explicit AND; adjacency is also AND
                if not self._peek() or self._peek()[0] in ("OR", "rp"):  # type: ignore[index]
                    break  # dangling AND → ignore (typo resilience)
            nodes.append(self._factor())
        return _combine(And, nodes)

    def _factor(self) -> Node:
        p = self._peek()
        if p is None:
            return Term("")  # nothing left (e.g. a lone '(') — empty, filtered by _combine
        if p[0] == "NOT":
            self._next()
            return Not(self._factor())
        if p and p[0] == "lp":
            self._next()
            inner = self._or()
            if self._peek() and self._peek()[0] == "rp":  # type: ignore[index]
                self._next()  # consume ')'; a missing one is tolerated
            return inner
        return self._atom()

    def _atom(self) -> Node:
        tok = self._next()
        kind, val = tok
        if kind == "phrase":
            return Term(val, phrase=True)
        if kind == "op":
            # A stray operator with no preceding field — treat its text as a term so a
            # malformed query still searches instead of erroring.
            return Term(val)
        # kind == 'word' (keyword words were only special in boolean position; here a
        # stray AND/OR/NOT-as-value is unlikely, but fall through to term just in case).
        word = val
        # A dotted path followed by an operator is a field predicate ATTEMPT, even if the
        # field is unknown — the compiler validates against the registry and 422s unknown
        # fields (§9.3: never a silent empty set). A bare dotted term (no op) stays a term.
        if _FIELD_PATH.fullmatch(word) and (nxt := self._peek()) and nxt[0] == "op":
            op = self._next()[1]
            value = self._read_value()
            return Field(word, op, value)
        if word.endswith("*") and len(word) > 1:
            return Term(word[:-1], prefix=True)
        return Term(word)

    def _read_value(self) -> str:
        p = self._peek()
        if p is None:
            return ""
        if p[0] in ("word", "phrase"):
            return self._next()[1]
        return ""  # op/paren where a value was expected → empty (lenient)


def parse_query(text: str) -> Node | None:
    """Parse operator input into the neutral AST. ``None`` for an empty query.

    Raises :class:`UnknownFieldError` only via the compiler, never here — the parser
    accepts any field name and the compiler validates against the registry so the
    caller can distinguish "bad field" (422) from "unparseable" (text fallback).
    """
    return _Parser(_tokenize(text)).parse()


def collect_fields(node: Node | None) -> list[str]:
    """Every dotted field referenced by the AST (for registry validation up front)."""
    if node is None:
        return []
    if isinstance(node, Field):
        return [node.field]
    if isinstance(node, Not):
        return collect_fields(node.child)
    if isinstance(node, (And, Or)):
        out: list[str] = []
        for c in node.children:
            out.extend(collect_fields(c))
        return out
    return []


__all__ = [
    "FIELD_REGISTRY",
    "And",
    "Field",
    "FieldSpec",
    "Not",
    "Or",
    "QueryParseError",
    "Term",
    "UnknownFieldError",
    "collect_fields",
    "parse_query",
]
