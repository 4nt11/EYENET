"""Shape tests for auth-resource schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import (
    AccessToken,
    LoginRequest,
    PATMinted,
    PATMintRequest,
    PATSummary,
    RefreshRequest,
    StreamTokenMinted,
    StreamTokenRequest,
    StreamTopic,
    SystemUserRole,
    TokenPair,
    UserMe,
)

pytestmark = pytest.mark.contract


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def uid() -> UUID:
    return UUID("01906f00-0000-7000-8000-000000000001")


# --- LoginRequest -----------------------------------------------------------


def test_login_request_happy() -> None:
    req = LoginRequest(username="anti", password="hunter2")
    assert req.username == "anti"


@pytest.mark.parametrize("missing", ["username", "password"])
def test_login_request_required(missing: str) -> None:
    payload = {"username": "anti", "password": "hunter2"}  # pragma: allowlist secret
    del payload[missing]
    with pytest.raises(PydanticValidationError):
        LoginRequest.model_validate(payload)


def test_login_request_min_length() -> None:
    with pytest.raises(PydanticValidationError):
        LoginRequest(username="", password="x")
    with pytest.raises(PydanticValidationError):
        LoginRequest(username="x", password="")


def test_login_request_rejects_extra() -> None:
    with pytest.raises(PydanticValidationError):
        LoginRequest.model_validate({"username": "u", "password": "p", "remember": True})


# --- RefreshRequest ---------------------------------------------------------


def test_refresh_request_min_length() -> None:
    with pytest.raises(PydanticValidationError):
        RefreshRequest(refresh_token="short")
    RefreshRequest(refresh_token="x" * 16)


# --- TokenPair / AccessToken -----------------------------------------------


def test_token_pair_defaults_token_type(now: datetime) -> None:
    pair = TokenPair(
        access_token="a",
        access_expires_at=now,
        refresh_token="r" * 16,
        refresh_expires_at=now,
    )
    assert pair.token_type == "Bearer"


def test_access_token_only(now: datetime) -> None:
    tok = AccessToken(access_token="a", access_expires_at=now)
    assert tok.token_type == "Bearer"


def test_token_pair_rejects_other_token_type(now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        TokenPair(
            access_token="a",
            access_expires_at=now,
            refresh_token="r" * 16,
            refresh_expires_at=now,
            token_type="JWT",  # type: ignore[arg-type]
        )


# --- UserMe -----------------------------------------------------------------


@pytest.mark.parametrize("role", list(SystemUserRole))
def test_user_me_accepts_every_role(uid: UUID, role: SystemUserRole) -> None:
    me = UserMe(user_id=uid, username="anti", role=role, scopes=["read:actors"])
    assert me.role is role


def test_user_me_rejects_unknown_role(uid: UUID) -> None:
    with pytest.raises(PydanticValidationError):
        UserMe.model_validate(
            {"user_id": str(uid), "username": "anti", "role": "godmode", "scopes": []},
        )


def test_user_me_default_scopes_empty(uid: UUID) -> None:
    me = UserMe(user_id=uid, username="anti", role=SystemUserRole.VIEWER)
    assert me.scopes == []


# --- PATs -------------------------------------------------------------------


def test_pat_mint_request_happy() -> None:
    req = PATMintRequest(name="scraper", scopes=["read:metrics"])
    assert req.scopes == ["read:metrics"]


def test_pat_mint_request_requires_at_least_one_scope() -> None:
    with pytest.raises(PydanticValidationError):
        PATMintRequest(name="scraper", scopes=[])


def test_pat_summary_optional_timestamps(uid: UUID, now: datetime) -> None:
    summary = PATSummary(
        token_id=uid,
        name="scraper",
        prefix="abc123",
        scopes=["read:metrics"],
        created_at=now,
    )
    assert summary.last_used_at is None
    assert summary.expires_at is None


def test_pat_minted_has_secret(uid: UUID, now: datetime) -> None:
    minted = PATMinted(
        token_id=uid,
        name="scraper",
        prefix="abc123",
        scopes=["read:metrics"],
        secret="eyenet_pat_abc123_secret",  # pragma: allowlist secret
        created_at=now,
    )
    assert minted.secret.startswith("eyenet_pat_")


# --- Stream token -----------------------------------------------------------


def test_stream_token_request_topics_required() -> None:
    with pytest.raises(PydanticValidationError):
        StreamTokenRequest(topics=[])


@pytest.mark.parametrize("topic", list(StreamTopic))
def test_stream_token_request_accepts_each_topic(topic: StreamTopic) -> None:
    req = StreamTokenRequest(topics=[topic])
    assert req.topics == [topic]


def test_stream_token_request_ttl_bounds() -> None:
    with pytest.raises(PydanticValidationError):
        StreamTokenRequest(topics=[StreamTopic.EYENET_AUDIT], ttl_seconds=30)
    with pytest.raises(PydanticValidationError):
        StreamTokenRequest(topics=[StreamTopic.EYENET_AUDIT], ttl_seconds=901)


def test_stream_token_minted(now: datetime) -> None:
    minted = StreamTokenMinted(
        stream_token="t",
        expires_at=now,
        topics=[StreamTopic.ATTRIBUTION_LINKAGE],
    )
    assert minted.topics == [StreamTopic.ATTRIBUTION_LINKAGE]
