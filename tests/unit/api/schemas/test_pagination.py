"""Shape tests for the generic `CursorPage[T]` wrapper."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import CursorPage, ProblemDetail

pytestmark = pytest.mark.contract


def test_cursor_page_happy_path_empty() -> None:
    page: CursorPage[ProblemDetail] = CursorPage.model_validate(
        {"items": [], "next_cursor": None},
    )
    assert page.items == []
    assert page.next_cursor is None
    assert page.estimated_total is None


def test_cursor_page_with_items_and_total() -> None:
    detail = {
        "type": "https://eyenet.local/errors/x",
        "title": "x",
        "status": 400,
        "request_id": "r",
    }
    page = CursorPage[ProblemDetail].model_validate(
        {"items": [detail], "next_cursor": "abc", "estimated_total": 42},
    )
    assert len(page.items) == 1
    assert page.next_cursor == "abc"
    assert page.estimated_total == 42


def test_cursor_page_rejects_extra() -> None:
    with pytest.raises(PydanticValidationError):
        CursorPage[ProblemDetail].model_validate({"items": [], "extra": "no"})


def test_cursor_page_negative_total_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        CursorPage[ProblemDetail].model_validate({"items": [], "estimated_total": -1})


def test_cursor_page_typed_item_validation() -> None:
    with pytest.raises(PydanticValidationError):
        CursorPage[ProblemDetail].model_validate({"items": [{"bogus": "row"}]})
