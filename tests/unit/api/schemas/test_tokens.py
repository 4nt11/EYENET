# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shape tests for PAT wire schemas (M9.A4)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas.auth import (
    CursorPagePATSummary,
    PATMinted,
    PATMintRequest,
    PATSummary,
)

pytestmark = pytest.mark.contract

_TS = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)


def test_mint_request_happy() -> None:
    req = PATMintRequest(name="prometheus-scrape", scopes=["read:metrics"])
    assert req.scopes == ["read:metrics"]
    assert req.expires_at is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "", "scopes": ["read:metrics"]},  # empty name
        {"name": "a" * 129, "scopes": ["read:metrics"]},  # name too long
        {"name": "ok", "scopes": []},  # at least one scope required
    ],
)
def test_mint_request_rejects(kwargs: dict[str, object]) -> None:
    with pytest.raises(PydanticValidationError):
        PATMintRequest(**kwargs)  # type: ignore[arg-type]


def test_minted_carries_secret_summary_does_not() -> None:
    # The one-time secret is on the mint response only; the summary (and the
    # mint response) never expose the at-rest hash.
    assert "secret" in PATMinted.model_fields
    assert "secret" not in PATSummary.model_fields
    assert "hash" not in PATSummary.model_fields
    assert "hash" not in PATMinted.model_fields


def test_summary_round_trip() -> None:
    summary = PATSummary(
        token_id=uuid4(),
        name="scrape",
        prefix="p" * 22,
        scopes=["read:metrics"],
        created_at=_TS,
    )
    assert summary.last_used_at is None
    assert summary.expires_at is None


def test_page_envelope_shape() -> None:
    page = CursorPagePATSummary(items=[], next_cursor=None, estimated_total=None)
    assert page.items == []
    assert page.next_cursor is None
