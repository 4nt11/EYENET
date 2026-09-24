# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operational-infrastructure indicator extraction (anti-spam linkage §B).

Templated spam defeats stylometric linkage: identical ad text = shared template,
not shared author. The discriminating signal is the *operational infrastructure*
embedded in the ads — contact handles, ``t.me`` links, crypto wallets — which
co-occurs across the accounts that actually belong to one crew. This module is the
pure extraction seam: text in, a set of typed indicator tokens out. No I/O, no DB
— so it is trivially testable and reusable by both a batch pass and a live sensor.

See ``development/linker-antispam-spec.md`` §3.
"""

from __future__ import annotations

import re

# Each indicator is a ``"<kind>:<value>"`` token so a single set/DF index spans
# all kinds. Values are normalized (lowercased where case is not significant) so
# @WBpay_MM1888 and @wbpay_mm1888 collapse to one indicator.
_HANDLE = re.compile(r"@([A-Za-z0-9_]{4,32})")
_TME = re.compile(r"t\.me/(\+?[A-Za-z0-9_/]{3,64})", re.IGNORECASE)
_WALLET_TRX = re.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b")  # TRON base58, case-sensitive
_WALLET_EVM = re.compile(r"\b0x[a-fA-F0-9]{40}\b")

# Handles that are structural noise, not crew infrastructure: bots/services every
# spammer @-mentions. Excluding them here is cheap; the linker also caps by
# document frequency (max_df) as the general guard.
_HANDLE_STOPLIST = frozenset({"admin", "everyone", "channel", "all", "here"})


def extract_indicators(text: str | None) -> set[str]:
    """Return the set of ``"<kind>:<value>"`` infrastructure indicators in ``text``.

    Kinds: ``handle`` (Telegram @username, case-folded), ``tme`` (t.me link,
    case-folded), ``wallet_trx`` (TRON, case-preserved), ``wallet_evm`` (EVM,
    case-folded). A message that mentions no infrastructure yields an empty set.
    """
    if not text:
        return set()
    out: set[str] = set()
    for h in _HANDLE.findall(text):
        low = h.lower()
        if low not in _HANDLE_STOPLIST:
            out.add(f"handle:{low}")
    for t in _TME.findall(text):
        out.add(f"tme:{t.lower().rstrip('/')}")
    for w in _WALLET_TRX.findall(text):
        out.add(f"wallet_trx:{w}")  # base58 is case-sensitive; do NOT fold
    for w in _WALLET_EVM.findall(text):
        out.add(f"wallet_evm:{w.lower()}")
    return out


__all__ = ["extract_indicators"]
