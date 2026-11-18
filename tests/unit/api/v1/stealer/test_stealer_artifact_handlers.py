# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call tests for the artifact drawer handlers (v1.3.3 + v1.3.4).

Covers the five /v1/stealer/artifacts routes + the artifact detail's
monitored-domain hit wiring. The reader is stubbed; this pins response
mapping + the initialized=False and 503 paths, not ClickHouse SQL.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from eyenet.api.deps import CurrentUser
from eyenet.api.v1.stealer import (
    api_artifact_domains as domains_mod,
    api_artifact_files as files_mod,
    api_artifact_records as records_mod,
    api_get_artifact as detail_mod,
    api_list_artifacts as list_mod,
)
from eyenet.api.v1.stealer._artifacts import reader as shared_reader
from eyenet.contracts.enums import SystemUserRole
from eyenet.stealer.query import (
    ArtifactCardRow,
    ArtifactDetailRow,
    ArtifactDomainRow,
    ArtifactFileRow,
    ArtifactRecordRow,
    StealerCorpusUninitializedError,
)

pytestmark = pytest.mark.unit

_SHA = "a" * 64


def _coro(value: object) -> object:
    """Wrap a value so the stubbed reader method returns an awaitable."""

    async def _inner(*_a: object, **_k: object) -> object:
        return value

    return _inner


def _raises(exc: BaseException) -> object:
    """Async stub that raises the given exception when awaited."""

    async def _inner(*_a: object, **_k: object) -> object:
        raise exc

    return _inner


def _user() -> CurrentUser:
    return CurrentUser(
        user_id=uuid4(),
        username="op",
        role=SystemUserRole.ANALYST,
        effective_scopes=frozenset({"read:stealer"}),
        token_expires_at=None,
    )


def _card(folder: str = "victim-01") -> ArtifactCardRow:
    return ArtifactCardRow(
        archive_sha256=_SHA,
        victim_folder=folder,
        country="US",
        traffic_affid="aff-42",
        build_version="1.0",
        creds_count=17,
        cookies_count=203,
        wallet_vaults_count=1,
        has_corporate_marker=True,
        has_wallet=True,
        has_crypter_banner=False,
    )


def _detail(hits: int = 3) -> ArtifactDetailRow:
    return ArtifactDetailRow(
        archive_sha256=_SHA,
        victim_folder="v-01",
        source="khazan",
        country="US",
        egress_ip="192.0.2.1",  # pragma: allowlist secret
        user_name="alice",
        computer_name="DESKTOP-X",
        os_version="win10",
        traffic_affid="aff-42",
        build_version="1.0",
        payload_md5="d" * 32,
        work_dir="C:\\Users\\alice",
        creds_count=17,
        cookies_count=203,
        autofills_count=5,
        history_count=100,
        downloads_count=4,
        processes_count=200,
        software_count=80,
        discord_tokens_count=1,
        steam_tokens_count=0,
        google_refresh_count=1,
        localstorage_jwt_count=2,
        wallet_vaults_count=1,
        has_corporate_marker=True,
        has_webmail_leak=False,
        has_wallet=True,
        has_crypter_banner=False,
        webmail_identity="",
        first_corporate_marker="acme.com",
        first_wallet_family="metamask",
        fired_rule_ids=["passwords_block_title"],
        monitored_domain_hits=hits,
    )


# -- list --


async def test_list_artifacts_maps_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shared_reader, "list_cards", _coro(([_card("a"), _card("b")], 2, 1)))
    resp = await list_mod.stealer_list_artifacts(_user())
    assert resp.initialized is True
    assert [c.victim_folder for c in resp.items] == ["a", "b"]
    assert resp.page_meta.total == 2
    assert resp.page_meta.has_more is False


async def test_list_artifacts_uninitialized_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        shared_reader, "list_cards", _raises(StealerCorpusUninitializedError("no table"))
    )
    resp = await list_mod.stealer_list_artifacts(_user())
    assert resp.initialized is False
    assert resp.items == []
    assert resp.page_meta.total == 0


# -- detail --


async def test_detail_maps_tiles_and_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detail_mod, "reader", _Fake(_detail(hits=5)))
    resp = await detail_mod.stealer_get_artifact(_user(), _SHA, "v-01")
    assert resp.stat_tiles.domain_hits == 5
    assert resp.stat_tiles.credentials == 17
    assert resp.stat_tiles.related == 0
    assert [t.technique_id for t in resp.techniques]  # passwords_block_title has TTPs


async def test_detail_404_when_reader_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detail_mod, "reader", _Fake(None))
    with pytest.raises(HTTPException) as ei:
        await detail_mod.stealer_get_artifact(_user(), _SHA, "v-01")
    assert ei.value.status_code == 404


async def test_detail_503_when_corpus_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detail_mod, "reader", _Boom())
    with pytest.raises(HTTPException) as ei:
        await detail_mod.stealer_get_artifact(_user(), _SHA, "v-01")
    assert ei.value.status_code == 503


# -- files --


async def test_files_maps_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        ArtifactFileRow(
            "v-01/Passwords.txt", "Passwords.txt", 2048, "passwords", True, 17, "URL: ...", "f" * 64
        ),
    ]
    monkeypatch.setattr(shared_reader, "file_tree", _coro(rows))
    resp = await files_mod.stealer_artifact_files(_user(), _SHA, "v-01")
    assert resp.items[0].filename == "Passwords.txt"
    assert resp.items[0].rows_emitted == 17


async def test_files_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        shared_reader, "file_tree", _raises(StealerCorpusUninitializedError("no table"))
    )
    with pytest.raises(HTTPException) as ei:
        await files_mod.stealer_artifact_files(_user(), _SHA, "v-01")
    assert ei.value.status_code == 503


# -- records --


async def test_records_maps_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        ArtifactRecordRow(
            rule_id="passwords_block_title",
            family="khazan",
            file_path="arch/v-01/Passwords.txt",
            fields={"url": "https://x", "username": "u", "password": "p"},
        )
    ]
    monkeypatch.setattr(shared_reader, "records", _coro((rows, 1, 1)))
    resp = await records_mod.stealer_artifact_records(_user(), _SHA, "v-01")
    assert resp.items[0].rule_id == "passwords_block_title"
    assert resp.items[0].fields["password"] == "p"
    assert resp.page_meta.total == 1


async def test_records_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        shared_reader, "records", _raises(StealerCorpusUninitializedError("no table"))
    )
    with pytest.raises(HTTPException) as ei:
        await records_mod.stealer_artifact_records(_user(), _SHA, "v-01")
    assert ei.value.status_code == 503


# -- domains --


async def test_domains_maps_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        ArtifactDomainRow(domain="accounts.google.com", source_kind="credential", count=4),
        ArtifactDomainRow(domain="facebook.com", source_kind="cookie", count=12),
    ]
    monkeypatch.setattr(shared_reader, "domains", _coro(rows))
    resp = await domains_mod.stealer_artifact_domains(_user(), _SHA, "v-01")
    assert [d.domain for d in resp.items] == ["accounts.google.com", "facebook.com"]
    assert resp.items[1].count == 12


async def test_domains_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        shared_reader, "domains", _raises(StealerCorpusUninitializedError("no table"))
    )
    with pytest.raises(HTTPException) as ei:
        await domains_mod.stealer_artifact_domains(_user(), _SHA, "v-01")
    assert ei.value.status_code == 503


# -- helpers --


class _Fake:
    def __init__(self, row: ArtifactDetailRow | None) -> None:
        self._row = row

    async def detail(self, *_a: object) -> ArtifactDetailRow | None:
        return self._row


class _Boom:
    async def detail(self, *_a: object) -> ArtifactDetailRow | None:
        raise StealerCorpusUninitializedError("no table")
