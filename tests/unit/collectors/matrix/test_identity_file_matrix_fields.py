"""IdentityFileEntry Matrix-field round-trip + session-check semantics."""

from __future__ import annotations

from pathlib import Path

import pytest

from eyenet.contracts.enums import IdentityState, SourceKind
from eyenet.identity_pool.loader import (
    IdentityFile,
    IdentityFileEntry,
    _uses_session_file,
    dump,
    load,
)


@pytest.mark.unit
def test_matrix_entry_round_trip(tmp_path: Path) -> None:
    entry = IdentityFileEntry(
        name="alpha_mx",
        source=SourceKind.MATRIX,
        matrix_homeserver_url="https://element.unredacted.org",
        matrix_user_id="@leroyjenkins:unredacted.org",
        matrix_access_token="secret-token-xyz",  # noqa: S106 — test fixture
        matrix_device_id="EYENET01",
        matrix_monitor_rooms=["!room1:server", "#alias:server"],
    )
    path = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), path)

    # Matrix entries don't need a session file on disk — loader must not
    # error on the missing-by-default session_path.
    parsed = load(path, check_session_files=True)
    assert len(parsed.identities) == 1
    out = parsed.identities[0]
    assert out.source == SourceKind.MATRIX
    assert out.matrix_homeserver_url == "https://element.unredacted.org"
    assert out.matrix_user_id == "@leroyjenkins:unredacted.org"
    assert out.matrix_access_token == "secret-token-xyz"  # noqa: S105 — test fixture
    assert out.matrix_device_id == "EYENET01"
    assert out.matrix_monitor_rooms == ["!room1:server", "#alias:server"]


@pytest.mark.unit
def test_telegram_entry_dump_unchanged_by_matrix_extension(tmp_path: Path) -> None:
    # Telegram-only entry must dump without spurious matrix_* lines.
    session = tmp_path / "tg.session"
    session.touch()
    entry = IdentityFileEntry(
        name="tg_alpha",
        source=SourceKind.TELEGRAM,
        session_path=str(session),
        telegram_api_id=12345,
        telegram_api_hash="deadbeef",
        monitor_groups=["@chan"],
        state=IdentityState.AVAILABLE,
    )
    path = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), path)
    text = path.read_text("utf-8")
    assert "matrix_homeserver_url" not in text
    assert "matrix_access_token" not in text
    assert "matrix_monitor_rooms" not in text
    assert "telegram_api_id = 12345" in text


@pytest.mark.unit
def test_uses_session_file_only_for_telegram() -> None:
    assert _uses_session_file(SourceKind.TELEGRAM) is True
    assert _uses_session_file(SourceKind.MATRIX) is False


@pytest.mark.unit
def test_mixed_source_toml_loads_without_telegram_session_for_matrix(tmp_path: Path) -> None:
    # When the TOML mixes Telegram + Matrix entries, the loader must still
    # check the Telegram session file but skip the check for Matrix.
    session = tmp_path / "tg.session"
    session.touch()
    tg = IdentityFileEntry(
        name="tg_alpha",
        source=SourceKind.TELEGRAM,
        session_path=str(session),
        telegram_api_id=1,
        telegram_api_hash="x",
    )
    mx = IdentityFileEntry(
        name="alpha_mx",
        source=SourceKind.MATRIX,
        matrix_homeserver_url="https://example.org",
        matrix_user_id="@a:example.org",
        matrix_access_token="t",  # noqa: S106 — test fixture
    )
    path = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[tg, mx]), path)

    parsed = load(path, check_session_files=True)
    names = {e.name for e in parsed.identities}
    assert names == {"tg_alpha", "alpha_mx"}
