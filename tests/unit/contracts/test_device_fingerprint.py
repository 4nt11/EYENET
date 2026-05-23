"""PLAN §6.1 — device fingerprint inputs are pinned per source kind."""

from __future__ import annotations

import pytest

from eyenet.contracts.enums import SourceKind
from eyenet.contracts.identity_pool import device_fingerprint


@pytest.mark.contract
def test_telegram_full_inputs() -> None:
    h = device_fingerprint(
        SourceKind.TELEGRAM,
        api_id=12345,
        device_model="Linux",
        system_version="6.18",
        app_version="1.0",
        lang_code="en",
        system_lang_code="en",
    )
    assert len(h) == 64


@pytest.mark.contract
def test_idempotent_kwarg_order() -> None:
    a = device_fingerprint(
        SourceKind.MATRIX,
        homeserver_url="https://m.example",
        device_id="ABCD",
        user_agent="ua",
    )
    b = device_fingerprint(
        SourceKind.MATRIX,
        user_agent="ua",
        device_id="ABCD",
        homeserver_url="https://m.example",
    )
    assert a == b


@pytest.mark.contract
def test_unknown_source_raises() -> None:
    with pytest.raises(ValueError, match="unknown source kind"):
        device_fingerprint("rss", whatever="x")


@pytest.mark.contract
def test_missing_field_raises() -> None:
    with pytest.raises(ValueError, match="missing="):
        device_fingerprint(SourceKind.TELEGRAM, api_id=1)


@pytest.mark.contract
def test_extra_field_raises() -> None:
    with pytest.raises(ValueError, match="extra="):
        device_fingerprint(
            SourceKind.MATRIX,
            homeserver_url="x",
            device_id="y",
            user_agent="z",
            bonus="nope",
        )


@pytest.mark.contract
def test_all_supported_kinds_have_schemas() -> None:
    # Every source kind that has a real collector listed in PLAN §6.1 must
    # have a schema. RSS / XMPP / DISCORD / etc may be added later; this
    # test only asserts the v0-pinned set is present.
    expected = {
        SourceKind.TELEGRAM,
        SourceKind.MATRIX,
        SourceKind.IRC,
        SourceKind.DISCORD,
        SourceKind.FORUM,
    }
    from eyenet.contracts.identity_pool import _DEVICE_FINGERPRINT_SCHEMAS

    assert expected <= set(_DEVICE_FINGERPRINT_SCHEMAS.keys())
