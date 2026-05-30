# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the shared cursor-pagination plumbing (M9.F5)."""

from __future__ import annotations

import pytest
from fastapi.exceptions import RequestValidationError

from eyenet.api.deps_paging import (
    CursorParams,
    cursor_params,
    decode_cursor,
    encode_cursor,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("offset", [0, 1, 42, 1000, 9_999_999])
def test_cursor_round_trip(offset: int) -> None:
    assert decode_cursor(encode_cursor(offset)) == offset


def test_decode_absent_cursor_is_zero() -> None:
    assert decode_cursor(None) == 0


def test_decode_rejects_non_base64() -> None:
    with pytest.raises(RequestValidationError):
        decode_cursor("not!base64!!")


def test_decode_rejects_non_integer_payload() -> None:
    # "YWJj" is valid base64url for "abc" — decodes cleanly but is not an integer
    with pytest.raises(RequestValidationError):
        decode_cursor("YWJj")


def test_decode_rejects_negative_offset() -> None:
    import base64

    neg = base64.urlsafe_b64encode(b"-1").decode("ascii")
    with pytest.raises(RequestValidationError):
        decode_cursor(neg)


def test_cursor_params_decodes_and_bundles() -> None:
    params = cursor_params(cursor=encode_cursor(50), limit=25, include_total=1)
    assert params == CursorParams(offset=50, limit=25, include_total=True)
    assert params.fetch_limit == 26


def test_cursor_params_defaults() -> None:
    params = cursor_params()
    assert params == CursorParams(offset=0, limit=50, include_total=False)


def test_next_cursor_advances_when_overfetch_has_more() -> None:
    params = CursorParams(offset=0, limit=50, include_total=False)
    # fetched fetch_limit (51) rows → there is a further page
    assert params.next_cursor(fetched=51) == encode_cursor(50)


def test_next_cursor_none_on_last_page() -> None:
    params = CursorParams(offset=100, limit=50, include_total=False)
    assert params.next_cursor(fetched=50) is None
    assert params.next_cursor(fetched=10) is None
