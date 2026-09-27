# SPDX-License-Identifier: AGPL-3.0-or-later
# ruff: noqa: RUF001, RUF003 — homoglyph fixtures intentionally use Cyrillic look-alikes.
"""Structural prefilter — hand-authored multilingual gold.

The point of the prefilter is language-neutrality: the prose can be EN/ES/RU/HI
but the structural token (onion, CVE, cred combo, wallet) is ASCII and fires
regardless. These rows are the trusted oracle the synthetic corpus is measured
against, not the other way round.

Recall gate, not verdict: a benign news article citing a CVE SHOULD pass (that
is correct — precision is the adjudicator's job). The only true negatives here
are structurally empty text and lone weak signals below threshold.
"""

from __future__ import annotations

import pytest

from eyenet.incidents.prefilter import scan

pytestmark = pytest.mark.unit


# (label, text) — should adjudicate. Signals ride under non-English prose.
_POSITIVE = [
    # RU brag: onion + credential combo.
    (
        "ru_onion_creds",
        "мы слили их базу, вот дамп: admin@corp-victim.ru:P@ssw0rd123 "
        "зеркало тут abcdefgh23456xyzqwmnbvcx.onion",
    ),
    # ES ransom brag: leak host + BTC wallet (medium + weak = 3).
    (
        "es_ransom_wallet",
        "Ciframos toda su red. El dump está en mega.nz y el pago va a "
        "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4 o no hay llaves.",
    ),
    # HI (Devanagari) brag: DB leak on a leak host + institutional target. Prose
    # is Hindi; the material signals (DATABASE, mega.nz, .gov.in) are ASCII.
    (
        "hi_db_leak",
        "हमने उनका पूरा DATABASE लीक कर दिया, dump यहाँ है mega.nz पर, टारगेट: portal.example.gov.in",
    ),
    # EN dump: 3-hash list (medium) + .sql dump (weak) = 3.
    (
        "en_hash_dump",
        "leaked their whole users table -> victim_db.sql "
        "d41d8cd98f00b204e9800998ecf8427e "
        "5d41402abc4b2a76b9719d911017c592 "
        "098f6bcd4621d373cade4e832627b4f6",
    ),
    # Real-shaped (field samples in dataset/data.md), anonymized:
    # Defacement banner + crew hashtag shoutout.
    (
        "deface_greetz",
        "HACKED BY EXAMPLE_BOSS: https://example-victim.example/ ❌\n"
        "Greetz:\n#Example_NX #EXAMPLE_BOSS #EXAM_DOM",
    ),
    # Leak-label + target + crew cluster ("DATABASE URL: ... #a #b").
    (
        "database_url_tags",
        "DATABASE\nURL: www.example-dairy.example\n#Example_NX #EXAMPLE_BOSS",
    ),
    # Big PII dump for sale: record count + PII schema + Session contact.
    (
        "airline_pii_sale",
        "full 2M ExampleAir (airlines) by @ex_ghost.7z\n"
        "membertitle firstname lastname passport nationality dob "
        "emailaddress primary_phone zip_code\n"
        "Contact Session: 05f3536077d949ad71ca61bb26562f873ef01d165d6ecdbc0e7815600975346150",
    ),
    # Data-for-sale one-liner: sale marker + dm contact.
    ("access_sold", "example-victim.example dm @some_team -sold-"),
    # DDoS down-claim: check-host.net proof link (strong, alone).
    (
        "ddos_checkhost",
        "\U0001f534 https://victim-airport.example/ DOWN\n"
        "https://check-host.net/check-report/4b4dd508k8ce\nDuration: 3 hours #CrewName",
    ),
    # Access-for-sale: WTS + webshell material on a gov target.
    ("wts_webshell", "WTS access login site portal.example.go.id, webshell go.id DM @seller"),
    # Compromise brag with an IP target list (multi_target medium + ipv4).
    (
        "ip_target_list",
        "several servers compromised, data extracted:\n"
        "https://194.145.53.82/\nhttps://34.247.232.235/\nhttps://52.51.97.45/",
    ),
    # Defacement mirror list ("Hacked List By …"), target text in Khmer.
    ("deface_list", "Hacked List System By CREW Team - ប្រព័ន្ធ DSpace"),
    # Stealer-log drop (the stealer/datadump category, not a brag).
    ("stealer_drop", "\U0001f680 NEW UPDATES! FRESH MATERIAL! LINK TO NEW UPLOAD L0G$ @logs_cloud"),
    # Stealer-cloud subscription: "Pass: t.me/chan" channel password.
    ("cloud_sub", "Pass: t.me/IckisCloud\nReserve this channel"),
    # Stealer drop by piece-count: "Logs [1200 Pcs]" + forwarded handle.
    (
        "logs_pcs_drop",
        "\U0001f4c1 Logs [MIXED-2026] [1200 Pcs] Part 2 forwarded from @premium_logs",
    ),
    # Breach announcement: "Data breach" label + record count + file host.
    (
        "breach_announce",
        "ARGENTINA PERSONAL - 129k [Citizens] Details of the Data breach - "
        "Full name, DNI. Download https://biteblob.com/x/#personal.db",
    ),
    # Homoglyph evasion: Cyrillic 'а' in "pаss" must fold to ASCII and still fire.
    ("homoglyph_pass", "pаss: @AltairSupport"),
    # DDoS bot command (launched attack, not a claim).
    ("ddos_cmd", "/attack https://city.example.gov.ph/ 70 flood"),
]

# (label, text) — should NOT adjudicate: no structural signal, or lone weak one.
_NEGATIVE = [
    ("es_benign", "Buenos días equipo, la reunión de sprint es a las 15:00, no falten."),
    ("ru_benign", "Кто-нибудь смотрел вчерашний матч? Счёт был безумный."),
    ("en_lone_ip", "the printer at 192.168.1.20 is jammed again, someone reboot it"),
    ("en_lone_handle", "great talk @conf_speaker, where are the slides?"),
    ("benign_logs", "can someone check the server logs? the app crashed again"),
    ("benign_pcs", "we still have 500 pcs of the t-shirts in stock, order now"),
    ("benign_attack_word", "let's attack this bug tomorrow, i'll dm the repo"),
    # Benign multi-link post: multi_target(2) alone must stay under the bar.
    (
        "benign_newsletter",
        "This week's reads: https://blog.example.com/a "
        "https://blog.example.com/b https://blog.example.com/c",
    ),
    ("empty", ""),
]


# (label, text) — the tool_sale signal must fire (crimeware tool/service for sale).
# Grounded in confirmed tooling gold; -> tooling in bootstrap_silver.
_TOOL_SALE = [
    ("ddos_script_sale", "FOR SALE ALL MY DDOS SCRIPT FOR A CHEAP PRICE DM @seller"),
    ("selling_ddos", "still selling ddos script"),
    ("stresser_layers", "NoLimitStresser - Layer 7 / Layer 4, dominate the application layer"),
    ("wormgpt_sale", "Sell File WormGpt List WormGPT Linux WormGPT Windows Price $4 DM @s"),
    ("service_drop", "New Service Drop! Now offering custom setups, build your own API CNC Panel"),
    ("wallet_scanner", "BeeChecker - Crypto Wallet Scanner, points at any folder, finds wallets"),
    ("buy_ddos", "To buy DD0S, contact @seller to purchase"),
    ("ddos_rps", "IM STILL SELLING DDOS SCRIPT WITH MILLION RPS USING SMALL PROXY DM @k"),
]

# (label, text) — tool_sale must STAY QUIET: hacktivist tool USE, or benign tool words.
_NOT_TOOL_SALE = [
    ("hacktivist_use", "we ddos'd the ministry site today, tango down 🇹🇭"),
    ("benign_loader_script", "reboot the server, the image loader script is stuck again"),
    ("benign_check", "can someone check the logs, the app crashed"),
    # crypter buyer-demand / chatter must NOT read as a tool SALE:
    ("crypter_demand", "i need crypter"),
    ("crypter_chatter", "Not crypter"),
]

# crypter WITH a sale/offer cue SHOULD fire (seller side, not buyer demand).
_CRYPTER_SALE = [
    ("crypter_fud_offer", "i got FUD Crypter if anyone's interested, dm me"),
    ("crypter_selling", "selling private crypter, fully undetected, price in dm"),
]


@pytest.mark.parametrize(("label", "text"), _TOOL_SALE, ids=[p[0] for p in _TOOL_SALE])
def test_tool_sale_fires(label: str, text: str) -> None:
    assert "tool_sale" in scan(text).signals, f"{label}: got {scan(text).signals}"


@pytest.mark.parametrize(("label", "text"), _NOT_TOOL_SALE, ids=[n[0] for n in _NOT_TOOL_SALE])
def test_tool_sale_stays_quiet(label: str, text: str) -> None:
    assert "tool_sale" not in scan(text).signals, f"{label}: got {scan(text).signals}"


@pytest.mark.parametrize(("label", "text"), _CRYPTER_SALE, ids=[p[0] for p in _CRYPTER_SALE])
def test_crypter_with_cue_fires(label: str, text: str) -> None:
    assert "tool_sale" in scan(text).signals, f"{label}: got {scan(text).signals}"


# Telecom / delivery-abuse service (-> tooling). Real operator-labeled samples plus variants.
_TELECOM = [
    ("bulk_sms", "WORLDWIDE BULK SMS SENDER. Faster routes for SMS deliveries 100% tested"),
    ("spoof_power", "UNLEASH UNLIMITED SPOOFING POWER, global coverage, any caller id"),
    ("voip_sip_setup", "DM @voipcxx for VoIP and SIP Setups, installation services"),
    ("cid_spoof", "caller id spoofing service, choose any number"),
    ("smtp_sender", "fresh SMTP sender + WEBMAILER + SENDGRID, customized Sender ID"),
    ("sip_trunk", "cheap sip trunk provider, unlimited routes"),
]
_NOT_TELECOM = [
    ("benign_sip", "let me sip my coffee and read this"),
    ("benign_otp", "you got an SMS with your login code, enter it to continue"),
    ("benign_smtp", "configure your smtp server host and port in settings"),
]


@pytest.mark.parametrize(("label", "text"), _TELECOM, ids=[p[0] for p in _TELECOM])
def test_telecom_abuse_fires(label: str, text: str) -> None:
    assert "telecom_abuse" in scan(text).signals, f"{label}: got {scan(text).signals}"


@pytest.mark.parametrize(("label", "text"), _NOT_TELECOM, ids=[n[0] for n in _NOT_TELECOM])
def test_telecom_abuse_stays_quiet(label: str, text: str) -> None:
    assert "telecom_abuse" not in scan(text).signals, f"{label}: got {scan(text).signals}"


@pytest.mark.parametrize(("label", "text"), _POSITIVE, ids=[p[0] for p in _POSITIVE])
def test_positive_adjudicates(label: str, text: str) -> None:
    res = scan(text)
    assert res.adjudicate, f"{label}: expected adjudicate, got signals={res.signals}"
    assert res.score >= 3


@pytest.mark.parametrize(("label", "text"), _NEGATIVE, ids=[n[0] for n in _NEGATIVE])
def test_negative_does_not_adjudicate(label: str, text: str) -> None:
    res = scan(text)
    assert not res.adjudicate, f"{label}: unexpected adjudicate, signals={res.signals}"


def test_signals_are_named_for_provenance() -> None:
    # A strong signal alone clears the bar and is reported by name.
    res = scan("mirror: abcdefgh23456xyzqwmnbvcx.onion")
    assert res.signals == ("onion_url",)
    assert res.adjudicate


def test_scan_never_raises_on_hostile_input() -> None:
    for junk in ("\x00\x00", "🙈" * 5000, "a" * 100_000, "@@@:::...onion"):
        scan(junk)  # must not raise
