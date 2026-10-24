# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stealer-log processing subsystem: password parse, archive extract, ULP → ClickHouse.

Productionizes the development/poc-tgmsg + poc-ulp prototypes. The Go extractor
(development/poc-ulp/ulpextract) is prod-grade and shipped as a binary; the password
parse and ingest logic are reimplemented here as first-class EYENET code.
"""
