"""Shape tests for `ProblemDetail` + `ValidationError` (§7)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import ProblemDetail, ValidationError

pytestmark = pytest.mark.contract


def _valid_problem(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "type": "https://eyenet.local/errors/not-found",
        "title": "Not found",
        "status": 404,
        "request_id": "01HXYZ",
    }
    base.update(overrides)
    return base


def test_problem_detail_happy_path_round_trips() -> None:
    payload = _valid_problem(detail="hello", instance="/v1/actors/x", trace_id="0" * 32)
    parsed = ProblemDetail.model_validate(payload)
    dumped = parsed.model_dump(exclude_none=True)
    # `errors` default is [] — accept it in the round-trip.
    payload["errors"] = []
    assert dumped == payload


def test_problem_detail_rejects_extra_fields() -> None:
    with pytest.raises(PydanticValidationError):
        ProblemDetail.model_validate(_valid_problem(unexpected="surprise"))


@pytest.mark.parametrize("missing", ["type", "title", "status", "request_id"])
def test_problem_detail_required_fields(missing: str) -> None:
    payload = _valid_problem()
    del payload[missing]
    with pytest.raises(PydanticValidationError) as exc_info:
        ProblemDetail.model_validate(payload)
    assert any(missing in str(loc) for err in exc_info.value.errors() for loc in err["loc"])


@pytest.mark.parametrize("status", [99, 600, -1])
def test_problem_detail_status_range(status: int) -> None:
    with pytest.raises(PydanticValidationError):
        ProblemDetail.model_validate(_valid_problem(status=status))


def test_problem_detail_trace_id_pattern() -> None:
    with pytest.raises(PydanticValidationError):
        ProblemDetail.model_validate(_valid_problem(trace_id="not-hex"))


def test_validation_error_shape() -> None:
    err = ValidationError(loc=["body", "username"], msg="missing", type="value_error.missing")
    assert err.loc == ["body", "username"]
    with pytest.raises(PydanticValidationError):
        ValidationError(loc=["body"], msg="m", type="t", extra="nope")  # type: ignore[call-arg]
