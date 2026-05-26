"""Unit tests for :func:`eyenet.util.domain.normalize_host`."""

from __future__ import annotations

import pytest

from eyenet.util.domain import normalize_host

# --- happy path ----------------------------------------------------------


@pytest.mark.unit
def test_lowercase_ascii_passthrough() -> None:
    assert normalize_host("foo.com") == "foo.com"


@pytest.mark.unit
def test_lowercases_mixed_case() -> None:
    assert normalize_host("Foo.COM") == "foo.com"


@pytest.mark.unit
def test_strips_leading_and_trailing_whitespace() -> None:
    assert normalize_host("   foo.com\t\n") == "foo.com"


@pytest.mark.unit
def test_strips_trailing_dot() -> None:
    assert normalize_host("foo.com.") == "foo.com"


@pytest.mark.unit
def test_strips_trailing_dot_after_whitespace() -> None:
    assert normalize_host("  foo.com.  ") == "foo.com"


# --- IDN / punycode ------------------------------------------------------


@pytest.mark.unit
def test_idn_encodes_to_punycode() -> None:
    # German "über.de" → xn--ber-goa.de (IDNA2008)
    out = normalize_host("über.de")
    assert out.startswith("xn--")
    assert out.endswith(".de")
    assert " " not in out
    assert out == out.lower()


@pytest.mark.unit
def test_idn_idempotent() -> None:
    once = normalize_host("über.de")
    twice = normalize_host(once)
    assert once == twice


@pytest.mark.unit
def test_existing_punycode_passes_through() -> None:
    # Already-encoded IDN must round-trip unchanged.
    assert normalize_host("xn--ber-goa.de") == "xn--ber-goa.de"


@pytest.mark.unit
def test_uppercase_punycode_lowercased() -> None:
    assert normalize_host("XN--BER-GOA.DE") == "xn--ber-goa.de"


# --- homograph defense ---------------------------------------------------


@pytest.mark.unit
def test_cyrillic_vs_latin_produce_distinct_canonical_forms() -> None:
    # "раура.com" with Cyrillic а (U+0430) vs Latin "paypa.com".  # noqa: RUF003
    # The defense is operator-visible distinction: they normalize to
    # *different* canonical strings, so an attacker spoofing a Source
    # cannot ride the same SourceDomain row as the legitimate one.
    latin = normalize_host("paypa.com")
    cyrillic = normalize_host("раура.com")  # noqa: RUF001
    assert latin == "paypa.com"
    assert cyrillic.startswith("xn--")
    assert latin != cyrillic


# --- mixed-form rejection -----------------------------------------------


@pytest.mark.unit
def test_rejects_mixed_xn_and_unicode() -> None:
    # Half punycoded, half unicode → ambiguous, reject.
    with pytest.raises(ValueError, match="ambiguous mixed-form"):
        normalize_host("xn--ber-goa.über.de")


# --- empty / invalid -----------------------------------------------------


@pytest.mark.unit
def test_empty_string_raises() -> None:
    with pytest.raises(ValueError, match="empty host"):
        normalize_host("")


@pytest.mark.unit
def test_whitespace_only_raises() -> None:
    with pytest.raises(ValueError, match="empty host"):
        normalize_host("   \t\n  ")


@pytest.mark.unit
def test_only_trailing_dot_raises() -> None:
    with pytest.raises(ValueError, match="empty host"):
        normalize_host(".")


@pytest.mark.unit
def test_invalid_idn_raises_value_error() -> None:
    # idna.IDNAError gets re-raised as ValueError so callers have one type.
    with pytest.raises(ValueError, match="invalid host"):
        normalize_host("foo..com")  # consecutive dots → empty label
