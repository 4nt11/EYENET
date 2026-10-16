#!/usr/bin/env python3
"""Probe: what does authenticated ThreatFox actually return? Structure only.

Run with your key sourced (never pass it on the CLI):
    ! set -a; source <your-dotfile>; set +a; \
      python3 development/poc-gliner/probe_threatfox.py

Prints query status, counts, and the FIELD NAMES of a sample entry so we can see
whether there's anything threat-GROUP-shaped (aliases / actor linkage) worth
wiring into the gazetteer. Prints no secrets and no bulk data.
"""
from __future__ import annotations

import json
import os
import urllib.request

API = "https://threatfox-api.abuse.ch/api/v1/"


def q(query: str) -> dict:
    key = os.environ.get("ABUSE_CH_APIKEY")
    if not key:
        raise SystemExit("ABUSE_CH_APIKEY not in env — source your dotfile first")
    req = urllib.request.Request(
        API, data=json.dumps({"query": query}).encode(),
        headers={"Auth-Key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 (fixed trusted URL)
        return json.loads(r.read())


def main() -> None:
    res = q("malware_list")
    print("query_status:", res.get("query_status"))
    data = res.get("data", {})
    print("type:", type(data).__name__, "| entries:", len(data))
    # show the shape of one entry (keys + a trimmed sample) to judge usefulness
    if isinstance(data, dict):
        k = next(iter(data))
        print("sample key:", k)
        print("sample fields:", json.dumps(data[k], ensure_ascii=False)[:400])
    elif isinstance(data, list) and data:
        print("sample fields:", json.dumps(data[0], ensure_ascii=False)[:400])


if __name__ == "__main__":
    main()
