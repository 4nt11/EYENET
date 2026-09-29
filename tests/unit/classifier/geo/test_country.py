"""Unit tests for victim-country attribution.

Two load-bearing properties:
1. **Title-first.** A poster-labeled title is ground truth and must override
   accidental body signals (the Argentine/Peru dumps full of 8-digit IDs that
   pass RUT mod-11 by chance).
2. **The dash gate.** A bare run of digits is any country's national ID; only a
   RUT written with its '-' before the check digit counts.
"""

from __future__ import annotations

import pytest

from eyenet.classifier.geo import classify_country

pytestmark = pytest.mark.unit


def test_title_country_name_outweighs_body() -> None:
    # Title says Russia; body has a valid CL RUT. The heavy title check wins.
    v = classify_country("cliente 12.345.678-5 aqui", title="Russia — Alfa Bank Database")
    assert v.country == "RU"
    assert v.decided_by == "country_name"


def test_title_demonym_resolves() -> None:
    v = classify_country("some dump", title="[ReichLeaks] TURKISH ISP COMPANY TURKNET 2.7M")
    assert v.country == "TR"


def test_title_cctld_resolves() -> None:
    v = classify_country("payload", title="credilink.com.br Financial Credit 2024")
    assert v.country == "BR"


def test_body_corroborates_matching_title() -> None:
    # Title CL + body RUT both point at CL: still CL, decided by the heavier check.
    v = classify_country("rut 12.345.678-5", title="RedClinica CHILE 120gb")
    assert v.country == "CL"
    assert v.decided_by == "country_name"


def test_title_uk_cctld_exception() -> None:
    v = classify_country("x", title="some-shop.co.uk customer dump")
    assert v.country == "GB"


def test_generic_tld_in_title_is_not_a_country() -> None:
    # .app is a gTLD, not a ccTLD — must not infer a country from it alone.
    v = classify_country("no body signals", title="motoboy.app leaked")
    assert v.status == "unknown"


def test_bare_number_without_dash_is_not_a_rut() -> None:
    # The Peru/Argentina false-positive class: 8-9 digit IDs, no dash. Must not vote.
    v = classify_country("dni 12345678 9 87654321 5 40123456", title=None)
    assert v.country is None
    assert v.status == "unknown"


def test_valid_rut_with_dash_resolves_from_body() -> None:
    # No title; a properly dashed, checksum-valid RUT resolves CL from body alone.
    v = classify_country("cliente 12.345.678-5 rut 11.111.111-1", title=None)
    assert v.country == "CL"
    assert v.decided_by == "national_id"


def test_bad_rut_check_digit_does_not_vote() -> None:
    v = classify_country("numero 12.345.678-9 y nada mas")
    assert v.status == "unknown"


def test_valid_iban_resolves_from_body() -> None:
    v = classify_country("wire to DE89370400440532013000 today")
    assert v.country == "DE"
    assert v.decided_by == "iban"


def test_phone_country_code_votes() -> None:
    v = classify_country("contacto +56 9 8765 4321 disponible")
    assert v.country == "CL"


def test_split_title_is_mixed() -> None:
    v = classify_country("x", title="Combo leak: Russia and Brazil merged")
    assert v.country is None
    assert v.status == "mixed"


def test_no_signals_is_unknown() -> None:
    v = classify_country("just prose, nothing structured", title="daily chat thread")
    assert v.country is None
    assert v.status == "unknown"


def test_evidence_is_masked_for_body_ids() -> None:
    v = classify_country("rut 12.345.678-5 here")
    body = [s for s in v.signals if s.kind == "national_id"]
    assert body and "12.345.678-5" not in body[0].evidence
