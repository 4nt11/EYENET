"""Unit tests for :func:`eyenet.util.domain.patterns_intersect`.

Every pairwise (k1, k2) combination is exercised, plus the
label-boundary regression cases that motivated the function in the first
place (``foo.com.endswith("oo.com")`` is True but they're different
domains).
"""

from __future__ import annotations

import pytest

from eyenet.contracts.enums import SourceDomainPatternKind as Kind
from eyenet.util.domain import patterns_intersect

# --- exact + exact ------------------------------------------------------


@pytest.mark.unit
def test_exact_exact_same() -> None:
    assert patterns_intersect("foo.com", Kind.EXACT, "foo.com", Kind.EXACT)


@pytest.mark.unit
def test_exact_exact_different() -> None:
    assert not patterns_intersect("foo.com", Kind.EXACT, "bar.com", Kind.EXACT)


# --- exact + subdomain_wildcard ----------------------------------------


@pytest.mark.unit
def test_exact_in_wildcard_subdomain() -> None:
    assert patterns_intersect(
        "x.foo.com",
        Kind.EXACT,
        "foo.com",
        Kind.SUBDOMAIN_WILDCARD,
    )


@pytest.mark.unit
def test_exact_apex_does_not_match_wildcard() -> None:
    # `*.foo.com` does NOT match `foo.com` itself.
    assert not patterns_intersect(
        "foo.com",
        Kind.EXACT,
        "foo.com",
        Kind.SUBDOMAIN_WILDCARD,
    )


@pytest.mark.unit
def test_exact_unrelated_does_not_match_wildcard() -> None:
    assert not patterns_intersect(
        "x.bar.com",
        Kind.EXACT,
        "foo.com",
        Kind.SUBDOMAIN_WILDCARD,
    )


# --- exact + suffix_match ----------------------------------------------


@pytest.mark.unit
def test_exact_equals_suffix() -> None:
    assert patterns_intersect(
        "foo.com",
        Kind.EXACT,
        "foo.com",
        Kind.SUFFIX_MATCH,
    )


@pytest.mark.unit
def test_exact_subdomain_of_suffix() -> None:
    assert patterns_intersect(
        "x.foo.com",
        Kind.EXACT,
        "foo.com",
        Kind.SUFFIX_MATCH,
    )


@pytest.mark.unit
def test_exact_unrelated_does_not_match_suffix() -> None:
    assert not patterns_intersect(
        "bar.com",
        Kind.EXACT,
        "foo.com",
        Kind.SUFFIX_MATCH,
    )


# --- wildcard + wildcard -----------------------------------------------


@pytest.mark.unit
def test_wildcard_same_parent_overlap() -> None:
    assert patterns_intersect(
        "foo.com",
        Kind.SUBDOMAIN_WILDCARD,
        "foo.com",
        Kind.SUBDOMAIN_WILDCARD,
    )


@pytest.mark.unit
def test_wildcard_nested_parents_overlap() -> None:
    # *.a.foo.com and *.foo.com both match "x.a.foo.com"
    assert patterns_intersect(
        "a.foo.com",
        Kind.SUBDOMAIN_WILDCARD,
        "foo.com",
        Kind.SUBDOMAIN_WILDCARD,
    )


@pytest.mark.unit
def test_wildcard_unrelated_parents_no_overlap() -> None:
    assert not patterns_intersect(
        "foo.com",
        Kind.SUBDOMAIN_WILDCARD,
        "bar.com",
        Kind.SUBDOMAIN_WILDCARD,
    )


# --- wildcard + suffix -------------------------------------------------


@pytest.mark.unit
def test_wildcard_same_as_suffix_overlap() -> None:
    assert patterns_intersect(
        "foo.com",
        Kind.SUBDOMAIN_WILDCARD,
        "foo.com",
        Kind.SUFFIX_MATCH,
    )


@pytest.mark.unit
def test_wildcard_subdomain_of_suffix_overlap() -> None:
    assert patterns_intersect(
        "a.foo.com",
        Kind.SUBDOMAIN_WILDCARD,
        "foo.com",
        Kind.SUFFIX_MATCH,
    )


@pytest.mark.unit
def test_suffix_subdomain_of_wildcard_overlap() -> None:
    assert patterns_intersect(
        "foo.com",
        Kind.SUBDOMAIN_WILDCARD,
        "a.foo.com",
        Kind.SUFFIX_MATCH,
    )


@pytest.mark.unit
def test_wildcard_unrelated_suffix_no_overlap() -> None:
    assert not patterns_intersect(
        "foo.com",
        Kind.SUBDOMAIN_WILDCARD,
        "bar.com",
        Kind.SUFFIX_MATCH,
    )


# --- suffix + suffix ---------------------------------------------------


@pytest.mark.unit
def test_suffix_same_overlap() -> None:
    assert patterns_intersect(
        "foo.com",
        Kind.SUFFIX_MATCH,
        "foo.com",
        Kind.SUFFIX_MATCH,
    )


@pytest.mark.unit
def test_suffix_nested_overlap() -> None:
    assert patterns_intersect(
        "a.foo.com",
        Kind.SUFFIX_MATCH,
        "foo.com",
        Kind.SUFFIX_MATCH,
    )


@pytest.mark.unit
def test_suffix_unrelated_no_overlap() -> None:
    assert not patterns_intersect(
        "foo.com",
        Kind.SUFFIX_MATCH,
        "bar.com",
        Kind.SUFFIX_MATCH,
    )


# --- label-boundary regression (the bug the Plan agent caught) --------


@pytest.mark.unit
def test_label_boundary_foo_vs_oo_does_not_match() -> None:
    # Naive str.endswith("oo.com") would say foo.com endswith oo.com,
    # but foo.com is NOT a subdomain of oo.com.
    assert not patterns_intersect(
        "foo.com",
        Kind.EXACT,
        "oo.com",
        Kind.SUBDOMAIN_WILDCARD,
    )


@pytest.mark.unit
def test_label_boundary_foo_vs_oo_suffix_does_not_match() -> None:
    assert not patterns_intersect(
        "foo.com",
        Kind.EXACT,
        "oo.com",
        Kind.SUFFIX_MATCH,
    )


@pytest.mark.unit
def test_label_boundary_two_wildcards_do_not_falsely_overlap() -> None:
    assert not patterns_intersect(
        "foo.com",
        Kind.SUBDOMAIN_WILDCARD,
        "oo.com",
        Kind.SUBDOMAIN_WILDCARD,
    )


# --- symmetry ---------------------------------------------------------


@pytest.mark.unit
def test_symmetry_exact_wildcard() -> None:
    a = patterns_intersect(
        "x.foo.com",
        Kind.EXACT,
        "foo.com",
        Kind.SUBDOMAIN_WILDCARD,
    )
    b = patterns_intersect(
        "foo.com",
        Kind.SUBDOMAIN_WILDCARD,
        "x.foo.com",
        Kind.EXACT,
    )
    assert a == b


@pytest.mark.unit
def test_symmetry_wildcard_suffix() -> None:
    a = patterns_intersect(
        "a.foo.com",
        Kind.SUBDOMAIN_WILDCARD,
        "foo.com",
        Kind.SUFFIX_MATCH,
    )
    b = patterns_intersect(
        "foo.com",
        Kind.SUFFIX_MATCH,
        "a.foo.com",
        Kind.SUBDOMAIN_WILDCARD,
    )
    assert a == b
