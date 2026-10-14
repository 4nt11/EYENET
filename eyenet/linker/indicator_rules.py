# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vendored default indicator-extraction rules (the seed catalog).

This is the single source of truth for the DEFAULT ruleset seeded into
``indicator_rule`` by the baseline-plus-incremental migrations. At runtime the
extractor reads rules from the DB (so operator toggles/custom rules apply); this
constant exists only to seed the vendored rows and for tests to assert the
catalog shipped.

Extractor value convention (implemented in the extractor, Phase 2): a rule whose
pattern has ONE capturing group yields ``match.group(1)`` as the value (e.g. the
``@handle`` without the ``@``); a rule with no capturing group yields the whole
match ``match.group(0)``. Only the handle rule uses a capturing group; every
other pattern below uses non-capturing ``(?:...)`` or none, so it stores the full
match.

``kind`` MUST be an :class:`~eyenet.contracts.enums.InfrastructureKind` value —
``infrastructure_artifact.kind`` is that typed enum.
"""

from __future__ import annotations

from typing import TypedDict


class VendoredRule(TypedDict):
    kind: str
    pattern: str
    fold_case: bool
    description: str


# fold_case is OFF for base58 kinds (TRON/Monero/BTC-legacy): base58 is
# case-significant, folding would corrupt the address and break dedup.
VENDORED_INDICATOR_RULES: tuple[VendoredRule, ...] = (
    {
        "kind": "handle_other_platform",
        "pattern": r"(?<![\w.%+-])@([A-Za-z0-9_]{4,32})\b",
        "fold_case": True,
        "description": "Telegram-style @handle; lookbehind excludes email domains",
    },
    {
        "kind": "wallet_eth",
        "pattern": r"\b0x[a-fA-F0-9]{40}\b",
        "fold_case": True,
        "description": "Ethereum / EVM address",
    },
    {
        "kind": "wallet_tron",
        "pattern": r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b",
        "fold_case": False,
        "description": "TRON base58 (USDT-TRC20 rail), case-sensitive",
    },
    {
        "kind": "wallet_btc",
        "pattern": r"\b[13][1-9A-HJ-NP-Za-km-z]{25,34}\b",
        "fold_case": False,
        "description": "Bitcoin legacy P2PKH/P2SH base58, case-sensitive",
    },
    {
        "kind": "wallet_btc",
        "pattern": r"\bbc1[a-z0-9]{25,62}\b",
        "fold_case": True,
        "description": "Bitcoin bech32 segwit",
    },
    {
        "kind": "wallet_xmr",
        "pattern": r"\b[48][0-9AB][1-9A-HJ-NP-Za-km-z]{93}\b",
        "fold_case": False,
        "description": "Monero standard address (95 chars), case-sensitive",
    },
    {
        "kind": "email",
        "pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "fold_case": True,
        "description": "Email / XMPP-Jabber (syntactically identical)",
    },
    {
        "kind": "pgp_key",
        "pattern": (
            r"-----BEGIN PGP (?:PUBLIC KEY|PRIVATE KEY|SIGNATURE) BLOCK-----"
            r"[\s\S]+?"
            r"-----END PGP (?:PUBLIC KEY|PRIVATE KEY|SIGNATURE) BLOCK-----"
        ),
        "fold_case": False,
        "description": "ASCII-armored PGP block (dedup by verbatim content)",
    },
    {
        "kind": "session",
        "pattern": r"\b05[0-9a-f]{64}\b",
        "fold_case": True,
        "description": "Session messenger ID (05 + 64 hex)",
    },
    {
        "kind": "tox",
        "pattern": r"\b[0-9A-Fa-f]{76}\b",
        "fold_case": True,
        "description": "Tox ID (76 hex)",
    },
)


__all__ = ["VENDORED_INDICATOR_RULES", "VendoredRule"]
