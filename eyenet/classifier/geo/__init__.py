"""Victim-country attribution for breach dumps (base signals + country overrides).

See :mod:`eyenet.classifier.geo._country`. Base layer (phone via libphonenumber,
IBAN mod-97) covers every country with no per-nation code; the override registry
adds checksummed national-ID precision for jurisdictions we operate in (CL today).
"""

from __future__ import annotations

from ._country import ENGINE_VERSION, CountrySignal, CountryVerdict, classify_country

__all__ = ["ENGINE_VERSION", "CountrySignal", "CountryVerdict", "classify_country"]
