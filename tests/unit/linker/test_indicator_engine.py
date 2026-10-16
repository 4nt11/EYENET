# SPDX-License-Identifier: AGPL-3.0-or-later
"""Indicator extraction engine: the vendored-catalog regexes + guards (pure)."""

from __future__ import annotations

import pytest

from eyenet.contracts.indicator import IndicatorRuleRow
from eyenet.linker.indicators import (
    compile_rules,
    default_ruleset,
    extract,
    extract_indicators,
)

pytestmark = pytest.mark.unit

_RULES = default_ruleset()


def _norms(text: str) -> set[str]:
    return extract_indicators(text)


def test_email_is_not_misextracted_as_handle() -> None:
    # The latent bug: @([\w]+) used to grab "gmail" out of "bob@gmail.com".
    got = _norms("reach me at Bob@Gmail.com please")
    assert "email:bob@gmail.com" in got
    assert not any(t.startswith("handle_other_platform:") for t in got)


def test_standalone_handle_still_extracts() -> None:
    assert "handle_other_platform:wbpay_desk" in _norms("ping @WBpay_desk now")


def test_btc_legacy_and_bech32() -> None:
    legacy = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"  # genesis P2PKH
    bech32 = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
    got = _norms(f"pay {legacy} or {bech32}")
    assert f"wallet_btc:{legacy}" in got  # base58 NOT folded
    assert f"wallet_btc:{bech32}" in got


def test_xmr_and_base58_case_preserved() -> None:
    # Real getmonero donation address (95 chars). Must be a genuine address: the
    # checksum gate (keccak-256) now rejects shape-only fakes.
    xmr = (
        "44AFFq5kSiGBoZ4NMDwYtN18obc8AemS33DBLWs3H7otXft3"
        "XjrpDtQGv7SqSsaBYBb98uNbr2VBBEt7f2wfn3RVGQBEP3A"
    )
    got = _norms(f"monero {xmr}")
    assert f"wallet_xmr:{xmr}" in got  # mixed-case preserved (fold_case off)


def test_session_and_tox_distinct_by_length() -> None:
    session = "05" + "a" * 64  # 66 chars
    tox = "A" * 76  # 76 hex
    got = _norms(f"session {session} tox {tox}")
    assert f"session:{session}" in got
    assert f"tox:{tox.lower()}" in got  # tox folds
    # tox (76) must not be mistaken for anything else; session stands alone.


def test_pgp_block_extracted_whole() -> None:
    block = (
        "-----BEGIN PGP PUBLIC KEY BLOCK-----\n"
        "mQINBGabc123\nsomekeymaterial==\n"
        "-----END PGP PUBLIC KEY BLOCK-----"
    )
    inds = extract(f"my key:\n{block}\nthanks", _RULES)
    pgp = [i for i in inds if i.kind == "pgp_key"]
    assert len(pgp) == 1
    assert pgp[0].value_raw.startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----")
    assert pgp[0].value_raw.endswith("-----END PGP PUBLIC KEY BLOCK-----")


def test_char_offset_points_at_match() -> None:
    text = "xx @alicehandle yy"
    inds = extract(text, _RULES)
    h = next(i for i in inds if i.kind == "handle_other_platform")
    assert text[h.char_offset :].startswith("alicehandle")  # offset points at the value
    assert h.value_norm == "alicehandle"


def test_dedup_within_message_keeps_first_offset() -> None:
    text = "@dupe here and @dupe again"
    inds = [i for i in extract(text, _RULES) if i.kind == "handle_other_platform"]
    assert len(inds) == 1
    assert inds[0].char_offset == 1  # first occurrence; value starts after '@' at 0


def test_compile_rules_skips_invalid_including_lookbehind() -> None:
    rows = [
        _rule("email", "(", True),  # bad syntax
        _rule("handle_other_platform", r"(?<!x)@y", True),  # lookbehind: RE2 rejects
        _rule("wallet_eth", r"\b0x[a-f0-9]{40}\b", True),  # good
    ]
    compiled, skipped = compile_rules(rows)
    assert len(compiled) == 1
    assert len(skipped) == 2


def _rule(kind: str, pattern: str, fold_case: bool) -> IndicatorRuleRow:
    from datetime import UTC, datetime

    now = datetime.now(tz=UTC)
    return IndicatorRuleRow(
        kind=kind,
        pattern=pattern,
        fold_case=fold_case,
        enabled=True,
        vendored=False,
        description="",
        created_at=now,
        updated_at=now,
    )
