"""Shape tests for the shared `WriteAccepted` 202 envelope."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import WriteAccepted

pytestmark = pytest.mark.contract


def test_write_accepted_happy() -> None:
    accepted = WriteAccepted(
        subject="attribution.linkage.confirmed",
        event_id=UUID("01906f00-0000-7000-8000-000000000001"),
        applied=False,
        poll="/v1/linkages/01906f00-0000-7000-8000-0000000000aa",
    )
    assert accepted.applied is False
    assert accepted.subject == "attribution.linkage.confirmed"


@pytest.mark.parametrize("missing", ["subject", "event_id", "applied", "poll"])
def test_write_accepted_required(missing: str) -> None:
    payload = {
        "subject": "x.y.z",
        "event_id": "01906f00-0000-7000-8000-000000000001",
        "applied": False,
        "poll": "/v1/x",
    }
    del payload[missing]
    with pytest.raises(PydanticValidationError):
        WriteAccepted.model_validate(payload)


def test_write_accepted_rejects_extra() -> None:
    with pytest.raises(PydanticValidationError):
        WriteAccepted.model_validate(
            {
                "subject": "x",
                "event_id": "01906f00-0000-7000-8000-000000000001",
                "applied": True,
                "poll": "/p",
                "extra": "nope",
            },
        )
