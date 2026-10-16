# SPDX-License-Identifier: AGPL-3.0-or-later
"""Crypto-address checksum gate: base58check / bech32 / EIP-55 / Monero.

The RE2 ruleset only shape-matches; base58 is near-superset of lowercase hex, so
a 32-char hex hash starting 1/3 with no '0' slips through the BTC pattern. This
pins that the coded checksum layer rejects it while real addresses survive.
"""

from __future__ import annotations

import pytest

from eyenet.linker._address_checksum import validate_address
from eyenet.linker.indicators import default_ruleset, extract_indicators

pytestmark = pytest.mark.unit

_RULES = default_ruleset()

# The exact string that triggered this work: an MD5/128-bit hex that the BTC
# legacy regex matched (starts '3', all base58-legal, no '0', 32 chars).
_MD5_CULPRIT = "3c38837bcd649592b2de5e87c3dbb3e2"

_VALID = [
    ("wallet_btc", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"),  # genesis P2PKH
    ("wallet_btc", "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"),  # P2SH
    ("wallet_btc", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"),  # bech32 v0
    ("wallet_tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"),  # USDT-TRC20
    ("wallet_eth", "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"),  # EIP-55 mixed
    ("wallet_eth", "0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed"),  # all-lower (no checksum)
    (
        "wallet_xmr",
        "44AFFq5kSiGBoZ4NMDwYtN18obc8AemS33DBLWs3H7otXft3"
        "XjrpDtQGv7SqSsaBYBb98uNbr2VBBEt7f2wfn3RVGQBEP3A",
    ),
]

_INVALID = [
    ("wallet_btc", _MD5_CULPRIT),  # the hash that started it
    ("wallet_btc", "1A1zP1eP5QGefi2DMPTfTL5SLmv7Divfna"),  # genesis, 1 char flipped
    ("wallet_tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6u"),  # bad checksum
    ("wallet_eth", "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1Beaed"),  # EIP-55 bad case
    ("wallet_xmr", "4" + "A" + "B" * 93),  # shape-valid, checksum garbage
]


@pytest.mark.parametrize(("kind", "value"), _VALID)
def test_valid_addresses_pass(kind: str, value: str) -> None:
    assert validate_address(kind, value) is True


@pytest.mark.parametrize(("kind", "value"), _INVALID)
def test_invalid_addresses_rejected(kind: str, value: str) -> None:
    assert validate_address(kind, value) is False


def test_non_crypto_kind_always_passes() -> None:
    assert validate_address("email", "bob@gmail.com") is True
    assert validate_address("handle_other_platform", "whatever") is True


def test_extract_drops_hash_keeps_real_btc() -> None:
    # Both are present in text; only the genuine address must become an artifact.
    text = f"hash {_MD5_CULPRIT} wallet 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    got = extract_indicators(text, _RULES)
    assert "wallet_btc:1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" in got
    assert f"wallet_btc:{_MD5_CULPRIT}" not in got
