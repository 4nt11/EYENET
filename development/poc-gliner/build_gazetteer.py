#!/usr/bin/env python3
"""Build a malware+threat-group gazetteer from two no-auth sources.

These entities are a CLOSED curated set -> dictionary match, not a model.
  - MITRE ATT&CK STIX: intrusion-set -> threat groups, malware -> families (APT-grade)
  - abuse.ch MalwareBazaar full CSV export: `signature` column -> commodity families
    (RedLine, Lumma, ...), which is what this corpus actually trades. No auth needed
    (the query API went auth-only in 2024; the bulk CSV export did not).

Malpedia would be the ideal third source but it's invite-only. Skipped.

    python development/poc-gliner/build_gazetteer.py   -> writes gazetteer.json
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
ATTACK_URL = "https://raw.githubusercontent.com/mitre/cti/master/enterprise-attack/enterprise-attack.json"
THREATFOX_API = "https://threatfox-api.abuse.ch/api/v1/"
# abuse.ch family names are CamelCase with a role suffix; forums use the bare stem.
SUFFIXES = ("Stealer", "RAT", "Bot", "Loader", "Ransomware", "Backdoor",
            "Miner", "Clipper", "Trojan", "Downloader", "Keylogger")

# Aliases that are real ATT&CK terms but too generic to match safely (common words,
# bare acronyms). ponytail: hand-curated floor, not exhaustive — grow it from the
# review dump's false positives rather than guessing the whole English dictionary.
STOP = {
    "rat", "bot", "tool", "team", "group", "pony", "carbon", "grease", "elise",
    "crimson", "babar", "hikit", "down", "it", "the", "wild", "flame", "comment",
    "sodium", "cobalt", "magic", "stealth", "shadow", "charming", "ke3chang",
    # common-English-word ATT&CK names observed as false positives in the PoC run:
    "play", "royal", "proton", "disco", "milan", "solar", "epic", "chaos",
    "calendar", "spark", "ramsay", "metamorfo", "clambling", "rising sun",
}


def keep(alias: str) -> bool:
    a = alias.strip()
    # len>=4 kills the noisiest 2-3 char acronyms; STOP kills curated-but-generic.
    return len(a) >= 4 and a.lower() not in STOP


def variants(name: str) -> set[str]:
    """A family name plus its suffix-stripped stem (RedLineStealer -> RedLine)."""
    out = {name}
    for suf in SUFFIXES:
        if name.endswith(suf) and len(name) - len(suf) >= 5:
            out.add(name[: -len(suf)])
    return out


def fetch_attack(gaz: dict[str, set[str]]) -> None:
    print(f"fetching ATT&CK ...")
    with urllib.request.urlopen(ATTACK_URL, timeout=120) as r:  # noqa: S310 (fixed trusted URL)
        bundle = json.loads(r.read())
    want = {"intrusion-set": "threat_group", "malware": "malware"}
    for obj in bundle.get("objects", []):
        cat = want.get(obj.get("type"))
        if not cat or obj.get("revoked") or obj.get("x_mitre_deprecated"):
            continue
        for n in [obj.get("name", "")] + list(obj.get("aliases", [])):
            if keep(n):
                gaz[cat].add(n.strip())


def fetch_threatfox(gaz: dict[str, set[str]]) -> None:
    # ThreatFox malware_list: clean {malware_printable, malware_alias} per family.
    # Malware only — abuse.ch has NO threat-actor list (confirmed via probe).
    key = os.environ.get("ABUSE_CH_APIKEY")
    if not key:
        print("skip ThreatFox: ABUSE_CH_APIKEY not set (ATT&CK-only gazetteer)")
        return
    print("fetching abuse.ch ThreatFox malware_list ...")
    req = urllib.request.Request(
        THREATFOX_API, data=json.dumps({"query": "malware_list"}).encode(),
        headers={"Auth-Key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 (fixed trusted URL)
        data = json.loads(r.read()).get("data", {})
    for info in data.values():
        names = [info.get("malware_printable") or ""]
        if info.get("malware_alias"):
            names += [a.strip() for a in info["malware_alias"].split(",")]
        for n in names:
            gaz["malware"].update(v for v in variants(n) if keep(v))


def main() -> None:
    gaz: dict[str, set[str]] = {"threat_group": set(), "malware": set()}
    fetch_attack(gaz)
    fetch_threatfox(gaz)
    out = {k: sorted(v) for k, v in gaz.items()}
    (HERE / "gazetteer.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"wrote gazetteer.json: {len(out['threat_group'])} groups, {len(out['malware'])} malware")


if __name__ == "__main__":
    main()
