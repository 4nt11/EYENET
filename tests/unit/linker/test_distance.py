"""Property and unit tests for hamming64 distance function."""

from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st

from eyenet.linker.comparators._distance import hamming64


def _hex64() -> st.SearchStrategy[str]:
    return st.binary(min_size=8, max_size=8).map(lambda b: b.hex())


@pytest.mark.unit
def test_identical_strings_are_distance_zero() -> None:
    h = "deadbeefcafebabe"
    assert hamming64(h, h) == 0


@pytest.mark.unit
def test_all_bits_flipped_is_64() -> None:
    assert hamming64("0000000000000000", "ffffffffffffffff") == 64


@pytest.mark.unit
def test_one_bit_diff_is_one() -> None:
    assert hamming64("0000000000000000", "0000000000000001") == 1


@pytest.mark.unit
def test_known_distance() -> None:
    # 0x0f vs 0x00 → 4 bits set in the XOR
    assert hamming64("000000000000000f", "0000000000000000") == 4


@pytest.mark.unit
def test_symmetry() -> None:
    a = "aabbccddeeff0011"
    b = "1122334455667788"
    assert hamming64(a, b) == hamming64(b, a)


@pytest.mark.unit
def test_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="16-char"):
        hamming64("deadbeef", "deadbeefcafebabe")


@pytest.mark.unit
def test_rejects_non_hex() -> None:
    with pytest.raises(ValueError, match="invalid literal"):
        hamming64("zzzzzzzzzzzzzzzz", "0000000000000000")


@pytest.mark.unit
@given(_hex64(), _hex64())
@settings(max_examples=500)
def test_non_negative(a: str, b: str) -> None:
    assert hamming64(a, b) >= 0


@pytest.mark.unit
@given(_hex64(), _hex64())
@settings(max_examples=500)
def test_bounded_by_64(a: str, b: str) -> None:
    assert hamming64(a, b) <= 64


@pytest.mark.unit
@given(_hex64(), _hex64())
@settings(max_examples=500)
def test_symmetric(a: str, b: str) -> None:
    assert hamming64(a, b) == hamming64(b, a)


@pytest.mark.unit
@given(_hex64())
@settings(max_examples=200)
def test_self_distance_is_zero(a: str) -> None:
    assert hamming64(a, a) == 0


@pytest.mark.unit
@given(_hex64(), _hex64(), _hex64())
@settings(max_examples=300)
def test_triangle_inequality(a: str, b: str, c: str) -> None:
    assert hamming64(a, c) <= hamming64(a, b) + hamming64(b, c)
