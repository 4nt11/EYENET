# SPDX-License-Identifier: AGPL-3.0-or-later
r"""Language-neutral structural prefilter — the cheap first gate of the cascade.

Pure and I/O-free (RE2, ReDoS-immune — the input is attacker-controlled group
chatter). It fires on the signals REAL brag posts actually carry, learned from
field samples, not a Hollywood idea of a threat actor:

- Defacement banners: ``HACKED BY <handle>``, ``Greetz:`` — the deface scene's
  lingua franca is English-ish regardless of the crew's native language.
- Crew hashtag/handle clusters: ``#AnaJak_NX #NIKK_BOSS #EXADOS`` shoutouts.
- Leak labels next to a victim: ``DATABASE`` / ``LEAK`` / ``DUMP`` + a target URL.
- Dumped material: credential combos, ``User:``/``Pw:`` pairs, hash lists, and
  the dump artifact itself (a ``victim.co.th.zip`` named after the target).
- Infra/payment: ``.onion`` mirrors, leak-drop hosts, wallet addresses.

CVEs are DELIBERATELY weak — leak/deface crews brag the result, not the method;
they barely cite CVEs. That was a corrected assumption ([[incident_prefilter_field_signals]]).

Contract: HIGH-RECALL gate, not a verdict. It decides only whether a message is
worth the more expensive adjudication (laya / LLM); it deliberately fires on
benign-but-structural text (a news article citing a CVE) — precision is the
adjudicator's job, downstream. ``scan`` never raises on any input.

RE2 word classes (\w \d \b) are ASCII-only; that is *correct* here — every token
(hashes, onion base32, wallets, hashtag handles) is ASCII. See
[[feedback_re2_ascii_word_classes]].
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Final

import re2

__all__ = ["ADJUDICATE_THRESHOLD", "SIGNALS", "PrefilterResult", "Signal", "scan"]

# Silence absl stderr; RE2 is linear-time so no per-call timeout is meaningful.
_RE2_OPTIONS = re2.Options()
_RE2_OPTIONS.log_errors = False

# Homoglyph fold: the scene swaps Latin letters for Cyrillic/Greek look-alikes
# (a Cyrillic a in "pass", a Cyrillic P in "Private") to dodge ASCII filters. We
# fold the common confusables to Latin on a scan-local copy before matching (stored
# text is untouched). Catches the evasion without a full Unicode-confusables table.
# See [[incident_prefilter_field_signals]].
# Built from code points (not literals) so the source carries no ambiguous-unicode
# characters. Each entry maps a confusable code point to its Latin look-alike.
_CONFUSABLE_POINTS: Final[dict[int, str]] = {
    # Cyrillic lowercase
    0x0430: "a",
    0x0435: "e",
    0x043E: "o",
    0x0440: "p",
    0x0441: "c",
    0x0445: "x",
    0x0443: "y",
    0x0456: "i",
    0x0458: "j",
    0x0455: "s",
    # Cyrillic uppercase
    0x0410: "A",
    0x0412: "B",
    0x0415: "E",
    0x041A: "K",
    0x041C: "M",
    0x041D: "H",
    0x041E: "O",
    0x0420: "P",
    0x0421: "C",
    0x0422: "T",
    0x0425: "X",
    # Greek
    0x03BF: "o",
    0x03B1: "a",
    0x03C1: "p",
    0x03BD: "v",
    0x039F: "O",
    0x0391: "A",
    0x03A1: "P",
}
_CONFUSABLES: Final = str.maketrans({chr(cp): latin for cp, latin in _CONFUSABLE_POINTS.items()})

# Weights: a STRONG signal alone clears the bar; medium+weak or 3x weak also do.
_STRONG: Final = 3
_MEDIUM: Final = 2
_WEAK: Final = 1
ADJUDICATE_THRESHOLD: Final = 3


@dataclass(frozen=True)
class Signal:
    """One structural detector: a compiled RE2 pattern and its weight."""

    name: str
    weight: int
    pattern: Any  # re2 pattern object; google-re2 ships no usable stubs.


def _sig(name: str, weight: int, pattern: str) -> Signal:
    return Signal(name=name, weight=weight, pattern=re2.compile(pattern, _RE2_OPTIONS))


# Ordered by weight. Patterns carry inline flags ((?i)); tokens are ASCII so \b
# is the intended ASCII boundary. Weights learned from real brag samples:
# defacement banners and leak-label+target are what actually fire, not CVEs.
SIGNALS: Final[tuple[Signal, ...]] = (
    # STRONG — the deface/leak scene's own signatures + unambiguous stolen material.
    #   "HACKED BY x", "0wned by x", "Greetz:" — English-ish scene lingua franca.
    _sig(
        "deface_banner",
        _STRONG,
        r"(?i)(?:\b(?:hacked|h4cked|0wned|owned|pwned|pwn3d|defaced|rooted|breached)\s+by\b"
        r"|\bgreet[sz]\b|\bmass[\s-]?deface\b|\bdeface(?:d|ment)?\s+by\b|\bhacked\s+list\b)",
    ),
    _sig("onion_url", _STRONG, r"(?i)\b[a-z2-7]{16,56}\.onion\b"),
    _sig("cred_combo", _STRONG, r"(?i)[\w.+-]{1,64}@[\w-]{1,63}\.[a-z]{2,24}:\S{3,64}"),
    #   Confirmed compromise (not sale material): "shell uploaded", "got root",
    #   "successfully breached/hacked", "backdoor deployed" — a done deed, alone enough.
    _sig(
        "compromise_confirmed",
        _STRONG,
        r"(?i)(?:\bshell\s+uploaded\b|\buploaded\s+(?:a\s+)?shell\b"
        r"|\bbackdoor\s+(?:installed|deployed|planted|up)\b|\bgot\s+(?:root|shell)\b"
        r"|\baccess\s+(?:gained|confirmed|granted)\b"
        r"|\bsuccessfully\s+(?:hacked|breached|compromised|defaced|pwned|breaked)\b)",
    ),
    #   check-host.net proof-of-down report — the DDoS scene's near-universal "TANGO
    #   DOWN" evidence link; effectively zero benign use.
    _sig("check_host", _STRONG, r"(?i)\bcheck-host\.net/check-report/\w+"),
    #   DDoS/attack bot COMMANDS: "/attack <target> 70 flood", "/scan <url>", "/ddos".
    #   Syntactic and unambiguous — a launched attack, not a claim. See incident-taxonomy.md.
    _sig(
        "ddos_command",
        _STRONG,
        r"(?im)(?:^|\s)/(?:attack|flood|ddos|dstat|stress|hit|scan)\s+"
        r"(?:https?://|\d{1,3}(?:\.\d{1,3}){3}|[a-z0-9-]+\.[a-z]{2,})\S*",
    ),
    # MEDIUM — corroborating scene shapes; two of them (or one + a weak) clear the bar.
    #   A cluster of 2+ hashtag handles = a crew shoutout ("#AnaJak_NX #NIKK_BOSS").
    _sig("crew_tag_cluster", _MEDIUM, r"(?i)#[a-z0-9_]{2,30}\b[\s,·|]{0,8}#[a-z0-9_]{2,30}\b"),
    #   Leak label near a victim: DB/leak/breach vocabulary, EN + ES.
    _sig(
        "leak_label",
        _MEDIUM,
        r"(?i)\b(?:database|base\s+de\s+datos|db\s?dump|dbs|full\s?dump|leaked"
        r"|data\s?breach|breach|registros|combo\s?list)\b",
    ),
    #   Stealer-cloud channel password: "Pass: @chan" / "pass - t.me/chan". Nobody
    #   writes this benignly; it is the subscription-service access handle.
    _sig("cloud_pass", _MEDIUM, r"(?i)\bpass\w*\s*[-:=]\s*(?:@|t\.me/)[a-z0-9_]{3,32}\b"),
    #   "User: … Pw: …" credential pair (EN/ES/RU labels).
    _sig(
        "cred_label",
        _MEDIUM,
        r"(?i)\b(?:user(?:name)?|usuario|login|логин)\b\s*[:=].{0,60}?"
        r"\b(?:pw|pass(?:word)?|пароль|clave)\b\s*[:=]",
    ),
    #   The dump artifact itself: a file named after the victim domain.
    _sig(
        "target_dump_file",
        _MEDIUM,
        r"(?i)\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\.(?:zip|rar|7z|sql|tar\.gz)\b",
    ),
    _sig(
        "leak_host",
        _MEDIUM,
        r"(?i)\b(?:pastebin\.com|ghostbin\.\w+|anonfiles\.\w+|mega\.nz|gofile\.io|privatebin\.\w+|dpaste\.\w+|transfer\.sh|file\.io|breachforums\.\w+|breached\.su|darkforums\.\w+|leakbase\.\w+|nulled\.\w+|cracked\.\w+|exposed\.vc|biteblob\.\w+)\b",
    ),
    # 3+ hex hashes in a row = a dumped hash/combo list, not an incidental id.
    _sig("hash_list", _MEDIUM, r"(?i)\b[a-f0-9]{32,64}\b(?:[\s,;|]+[a-f0-9]{32,64}\b){2,}"),
    #   Data-for-sale: "WTS/WTB", "for sale", "-sold-", "price:", "vendo", "продам".
    _sig(
        "sale_marker",
        _MEDIUM,
        r"(?i)(?:\b(?:wts|wtb|for\s?sale|selling|sold|vendo|продам)\b|-\s?sold\s?-|\bprice\s*[:=])",
    ),
    #   Access-for-sale material: webshell / RDP / RCE / root|admin access / cpanel.
    _sig(
        "access_material",
        _MEDIUM,
        r"(?i)\b(?:webshell|web\s?shell|rce|reverse\s?shell|shell\s?access"
        r"|rdp|smtp|cpanel|(?:root|admin|full)\s?access|c99|r57|wso)\b",
    ),
    #   Crimeware TOOL/SERVICE for sale (-> tooling): distinct product nouns
    #   (booter/stresser/wormgpt/crypter/scampage/botnet) fire on sight; ambiguous
    #   ones (ddos/L7/L4) require a sale/product cue so hacktivist USE ("we ddos'd X")
    #   stays quiet. Grounded in the confirmed tooling gold (DDoS scripts, stressers,
    #   WormGPT, checkers, "service drop / build your own", CNC panels).
    _sig(
        "tool_sale",
        _MEDIUM,
        r"(?i)(?:"
        r"booter|stress?er|wormgpt|scam\s?page|scampage"
        r"|\bkeylogger\b|\bbotnet\b|\botp\s?bot\b|\bstealer\s?(?:builder|source)\b"
        r"|\bloader\s?builder\b"
        # crypter is buyer-demand-prone ("i need crypter") -> require a sale/offer cue.
        r"|\bcrypter\b[^\n]{0,40}?\b(?:sell\w*|for\s?sale|fud|cracked|price|rent|sub\w*|stock|promo|interested|offer\w*)\b"
        r"|\b(?:sell\w*|for\s?sale|fud|cracked|price|stock|promo|interested|offer\w*)\b[^\n]{0,40}?\bcrypter\b"
        r"|\b(?:dd[o0]s|dstat|l7|l4|layer\s?[47])\b[^\n]{0,45}?\b(?:script|setup|service|panel|method|rps|plan|subscription|for\s?sale|selling|sell|buy|purchase|rent|cloudflare)\b"
        r"|\b(?:for\s?sale|selling|sell|buy|purchase|updated)\b[^\n]{0,45}?\b(?:dd[o0]s|l7|l4)\b"
        r"|\b(?:selling|for\s?sale|jual|rent|buy)\b[^\n]{0,45}?\b(?:script|software|tool|method|checker|scanner|builder|source|course|config)\b"
        r"|\bservice\s?drop\b|\bcnc\s?panel\b|\bwallet\s?scanner\b|\baccount\s?recovery\b"
        r"|\bbuild\s?your\s?own\b[^\n]{0,30}?\b(?:cnc|api|panel|setup|booter|stress?er)\b"
        r")",
    ),
    #   Telecom / delivery-abuse SERVICE (-> tooling today; a telecom_abuse leaf later,
    #   see development/incident-taxonomy-hierarchy.md). SIP/VoIP trunking, bulk-SMS
    #   senders, caller-ID spoofing, SMTP/SendGrid senders — a fraud-enablement service,
    #   NOT initial access brokerage. Bare "sms"/"sip"/"smtp" are anchored to an abuse
    #   noun so benign chatter ("sip your coffee", "SMS you got a code") stays quiet.
    _sig(
        "telecom_abuse",
        _MEDIUM,
        r"(?i)(?:"
        r"\b(?:cid|caller[\s-]?id)\s?spoof\w*|\bspoof(?:ed|ing)?\b[^\n]{0,20}?\b(?:call|caller|cid|number)\b"
        r"|\bunlimited\s+spoofing\b|\bspoofing\s+power\b"
        r"|\b(?:voip|sip)\b[^\n]{0,20}?\b(?:trunk|setup|route|provider|gateway|panel|dialer|dial|access)\w*"
        r"|\bbulk\s?sms\b|\bsms\s?(?:sender|blast|route|gateway|marketing|deliver\w*|spam)\b"
        r"|\bmass\s?(?:sms|text)\b|\bsender\s?id\b"
        r"|\bsendgrid\b|\bweb\s?mailer\b|\bmass\s?mail\w*"
        r"|\bsmtp\s?(?:sender|blast|cracked|combo|inbox|spam)\b"
        r")",
    ),
    #   3+ distinct targets in one post (URL list or IP list) = an attack target dump.
    _sig(
        "multi_target",
        _MEDIUM,
        r"(?is)(?:(?:https?://\S+\s+){2}https?://\S+)"
        r"|(?:(?:(?:\d{1,3}\.){3}\d{1,3})\D*){3}",
    ),
    #   Infostealer-log / combolist drops: family names, "fresh logs/material",
    #   L0G$ leetspeak, UHQ, url:log:pass format. The stealer/datadump category.
    _sig(
        "stealer_logs",
        _MEDIUM,
        r"(?i)(?:\b(?:stealer|redline|lumma|raccoon|vidar|risepro|stealc|meta\s?stealer)\b"
        r"|\bl0g[s$]|\bfresh\s?(?:logs?|material|clouds?)\b|\bcloud\s?logs?\b|\buhq\b"
        r"|\bu\.?l\.?p\b|\b\d[\d.,]*\s?lines\b"
        # "Logs [1200 Pcs]" — a piece-count of logs near the word logs = a stealer drop
        r"|(?is:\blogs?\b.{0,30}?\b\d[\d,]*\s*(?:pcs|pieces|pzs)\b)"
        r"|\burl[:\s|]+(?:log|user|mail)[:\s|]+pass\b)",
    ),
    #   A leaked PII table header: 3+ column names in a row ("firstname lastname passport …").
    _sig(
        "pii_schema",
        _MEDIUM,
        r"(?i)(?:\b(?:firstname|lastname|middlename|passport|passexpiry|nationality|dob|emailaddress|primary_phone|second_phone|zip_code|marital|jobtitle|national_id|ssn|cardnumber|cvv)\b[\s,|]+){3,}",
    ),
    #   Session Messenger contact id (05 + 64 hex) — the "dm me to buy" handle.
    _sig("session_id", _MEDIUM, r"(?i)\b05[a-f0-9]{64}\b"),
    #   High-value institutional victim by TLD. Covers Anglo (gov/mil/int/edu),
    #   Indonesian (go.id), Spanish (gob.xx), French (gouv.xx), academic (ac.xx).
    _sig(
        "institutional_target",
        _MEDIUM,
        r"(?i)\b[a-z0-9.-]+\.(?:gov|mil|int|edu"
        r"|(?:gov|gob|gouv|go|mil|ac|edu)\.[a-z]{2})\b",
    ),
    # WEAK — need company to clear the bar. CVE is weak: crews brag results, not methods.
    _sig("cve", _WEAK, r"(?i)\bCVE-\d{4}-\d{4,7}\b"),
    _sig("btc_addr", _WEAK, r"\b(?:bc1[a-z0-9]{25,59}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b"),
    _sig("eth_addr", _WEAK, r"(?i)\b0x[a-f0-9]{40}\b"),
    _sig("ipv4", _WEAK, r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
    _sig("tg_target", _WEAK, r"(?i)(?:\bt\.me/|@)[a-z0-9_]{4,32}\b"),
    #   Record-count boast: "2M", "500k", "1.2 million records/rows/lines".
    _sig(
        "record_count",
        _WEAK,
        r"(?i)\b\d[\d.,]*\s?(?:kk|k|m|mil|mill?ion|millones|млн|records|rows|lines|entries)\b",
    ),
    #   "dm @handle" / "dm to buy" — contact-to-transact.
    _sig("dm_contact", _WEAK, r"(?i)\bdm\s+@?[a-z0-9_]{3,32}\b"),
)


@dataclass(frozen=True)
class PrefilterResult:
    """Which structural signals fired, their summed weight, and the gate decision."""

    signals: tuple[str, ...]
    score: int
    adjudicate: bool


def scan(text: str) -> PrefilterResult:
    """Run every structural signal over ``text`` and decide whether to adjudicate.

    Text is NFC-normalized once so composed/decomposed forms match identically.
    ``adjudicate`` is true when any STRONG signal fires or the summed weight
    reaches :data:`ADJUDICATE_THRESHOLD`. The fired signal names are returned for
    the incident record's provenance and to prime the adjudicator's context.
    """
    normalized = unicodedata.normalize("NFC", text).translate(_CONFUSABLES)
    fired: list[str] = []
    score = 0
    for sig in SIGNALS:
        if sig.pattern.search(normalized) is not None:
            fired.append(sig.name)
            score += sig.weight
    return PrefilterResult(
        signals=tuple(fired),
        score=score,
        adjudicate=score >= ADJUDICATE_THRESHOLD,
    )
