"""_bag utility — tokenize, function-word vector, char trigrams, cosine."""

from __future__ import annotations

import pytest

from eyenet.verifier.verifiers._bag import (
    char_trigram_vector,
    char_trigrams,
    cosine,
    function_word_vector,
    tokenize,
)


@pytest.mark.unit
def test_tokenize_lowercase_and_word_boundaries() -> None:
    assert tokenize("Hello, World!") == ["hello", "world"]


@pytest.mark.unit
def test_function_word_vector_sums_to_one_when_nonempty() -> None:
    fw = function_word_vector(["la casa de mi madre"], language="es")
    assert pytest.approx(sum(fw.values())) == 1.0


@pytest.mark.unit
def test_function_word_vector_empty_on_no_function_words() -> None:
    fw = function_word_vector(["XYZ ABC"], language="es")
    assert fw == {}


@pytest.mark.unit
def test_char_trigrams_count_correctly() -> None:
    c = char_trigrams("abcd")
    # "abc", "bcd"
    assert c["abc"] == 1
    assert c["bcd"] == 1


@pytest.mark.unit
def test_char_trigram_vector_normalizes() -> None:
    v = char_trigram_vector(["abcabc"])
    assert pytest.approx(sum(v.values())) == 1.0


@pytest.mark.unit
def test_cosine_zero_on_empty_input() -> None:
    assert cosine({}, {"x": 1.0}) == 0.0
    assert cosine({"x": 1.0}, {}) == 0.0


@pytest.mark.unit
def test_cosine_identical_is_one() -> None:
    v = {"a": 0.5, "b": 0.5}
    assert pytest.approx(cosine(v, v)) == 1.0


@pytest.mark.unit
def test_cosine_orthogonal_is_zero() -> None:
    assert cosine({"a": 1.0}, {"b": 1.0}) == 0.0
