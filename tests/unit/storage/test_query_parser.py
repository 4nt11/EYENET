# SPDX-License-Identifier: AGPL-3.0-or-later
"""Neutral query-language parser — grammar + fuzz (GLOBAL_SEARCH.md §9.2/§9.4).

Pure-AST tests: no SQL, no storage. The security property (no input escapes the
binder) is verified at the compiler layer; here we assert the grammar parses the
documented shapes and that NO input makes the parser raise (typo resilience)."""

from __future__ import annotations

import random
import string

import pytest

from eyenet.storage.query import (
    And,
    Field,
    Not,
    Or,
    Term,
    collect_fields,
    parse_query,
)

pytestmark = pytest.mark.unit


def test_bare_term() -> None:
    assert parse_query("zfo") == Term("zfo")


def test_phrase() -> None:
    assert parse_query('"school database"') == Term("school database", phrase=True)


def test_prefix() -> None:
    assert parse_query("zfo*") == Term("zfo", prefix=True)


def test_implicit_and() -> None:
    assert parse_query("a b") == And((Term("a"), Term("b")))


def test_explicit_and_or() -> None:
    assert parse_query("a AND b") == And((Term("a"), Term("b")))
    assert parse_query("a OR b") == Or((Term("a"), Term("b")))


def test_not() -> None:
    assert parse_query("NOT a") == Not(Term("a"))


def test_lowercase_keywords() -> None:
    assert parse_query("a and b") == And((Term("a"), Term("b")))
    assert parse_query("a or b") == Or((Term("a"), Term("b")))


def test_c_style_boolean_aliases() -> None:
    assert parse_query("a && b") == And((Term("a"), Term("b")))
    assert parse_query("a || b") == Or((Term("a"), Term("b")))
    assert parse_query("a&&b") == And((Term("a"), Term("b")))  # glued
    assert parse_query("message.author == zfo || message.author == pampa") == Or(
        (Field("message.author", "==", "zfo"), Field("message.author", "==", "pampa"))
    )


@pytest.mark.parametrize(
    ("q", "op"),
    [
        ("message.author == zfo", "=="),
        ("message.author != zfo", "!="),
        ("message.author =~ zfo", "=~"),
        ("message.content : zfo", ":"),
    ],
)
def test_field_predicate_spaced(q: str, op: str) -> None:
    assert parse_query(q) == Field("message.author" if op != ":" else "message.content", op, "zfo")


def test_field_predicate_glued() -> None:
    assert parse_query("message.author==zfo") == Field("message.author", "==", "zfo")
    assert parse_query("message.author=~zfo") == Field("message.author", "=~", "zfo")
    assert parse_query("group.status!=joined") == Field("group.status", "!=", "joined")


def test_field_predicate_quoted_value() -> None:
    assert parse_query('case.title == "la pampa"') == Field("case.title", "==", "la pampa")


def test_url_value_not_split_on_colon() -> None:
    # the "://" scheme colon must NOT be read as the ':' operator
    assert parse_query("https://t.me/zfo") == Term("https://t.me/zfo")
    assert parse_query("artifact.value =~ t.me/zfo") == Field("artifact.value", "=~", "t.me/zfo")


def test_grouping_and_precedence() -> None:
    got = parse_query("ransomware AND (group.status == monitored OR group.status == joined)")
    assert got == And(
        (
            Term("ransomware"),
            Or((Field("group.status", "==", "monitored"), Field("group.status", "==", "joined"))),
        )
    )


def test_collect_fields() -> None:
    got = parse_query("a AND (message.author == zfo OR group.status != joined)")
    assert sorted(collect_fields(got)) == ["group.status", "message.author"]


def test_empty_query_is_none() -> None:
    assert parse_query("") is None
    assert parse_query("   ") is None


def test_dangling_operator_degrades() -> None:
    # a trailing AND must not raise (§9.4 typo resilience)
    assert parse_query("zfo AND") == Term("zfo")
    assert parse_query("message.author ==") == Field("message.author", "==", "")


def test_unknown_field_parses_as_predicate_for_422() -> None:
    # unknown dotted field + op parses to a Field so the COMPILER can 422 it (§9.3),
    # rather than silently degrading to a term.
    node = parse_query("bogus.field == x")
    assert node == Field("bogus.field", "==", "x")
    assert collect_fields(node) == ["bogus.field"]


def test_fuzz_never_raises() -> None:
    alphabet = string.ascii_letters + string.digits + ' ()"=!:*.~/|&_-'
    rnd = random.Random(1234)  # noqa: S311 — fuzz input, not cryptographic
    for _ in range(4000):
        s = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 40)))
        parse_query(s)  # must never raise, whatever the garbage
