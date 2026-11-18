# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for FileAuditReader pure helpers (v1.2.7).

The CH-touching methods have end-to-end coverage via integration; here we pin
the pagination arithmetic that drives the FE's "Page M of N" render. Getting
page_count wrong at a page/limit boundary is an off-by-one that looks fine
locally and annoys operators."""

from __future__ import annotations

import pytest

from eyenet.stealer.query import FileAuditReader

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("total", "limit", "expected"),
    [
        (0, 25, 0),  # empty table
        (1, 25, 1),  # single row, one page
        (25, 25, 1),  # exactly one page, no overflow
        (26, 25, 2),  # one over
        (50, 25, 2),  # exactly two pages
        (51, 25, 3),  # one over two
        (1000, 10, 100),  # round
        (1001, 10, 101),  # one over round
        (99, 100, 1),  # limit > total
        (100, 100, 1),  # exact
        (101, 100, 2),  # one into second page
    ],
)
def test_page_count_rounds_up(total: int, limit: int, expected: int) -> None:
    assert FileAuditReader._page_count(total, limit) == expected


@pytest.mark.parametrize(
    ("page", "limit", "expected_offset"),
    [
        (1, 25, 0),
        (2, 25, 25),
        (3, 25, 50),
        (1, 100, 0),
        (10, 10, 90),
        # page=0 would be invalid at the API layer; the helper clamps to 0
        (0, 25, 0),
        (-5, 25, 0),
    ],
)
def test_window_offset(page: int, limit: int, expected_offset: int) -> None:
    assert FileAuditReader._window(page, limit) == expected_offset
