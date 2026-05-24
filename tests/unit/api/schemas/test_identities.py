"""Shape tests for IdentityActionRequest + PanicRequest."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import IdentityActionRequest, PanicRequest

pytestmark = pytest.mark.contract


def test_identity_action_request_minimal() -> None:
    req = IdentityActionRequest(reason="rotated key")
    assert req.note is None


def test_identity_action_request_reason_required() -> None:
    with pytest.raises(PydanticValidationError):
        IdentityActionRequest(reason="")


def test_identity_action_request_rejects_extra() -> None:
    with pytest.raises(PydanticValidationError):
        IdentityActionRequest.model_validate({"reason": "r", "secret": "s"})


def test_panic_request_requires_confirm_literal() -> None:
    PanicRequest(reason="incident", confirm="I_UNDERSTAND")


@pytest.mark.parametrize("bad", ["yes", "I_understand", "I-UNDERSTAND", "", "ok"])
def test_panic_request_rejects_wrong_confirm(bad: str) -> None:
    with pytest.raises(PydanticValidationError):
        PanicRequest(reason="incident", confirm=bad)  # type: ignore[arg-type]


def test_panic_request_reason_required() -> None:
    with pytest.raises(PydanticValidationError):
        PanicRequest.model_validate({"confirm": "I_UNDERSTAND"})
