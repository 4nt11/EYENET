#!/usr/bin/env python3
"""Sample high-yield labeling candidates from the extracted corpus, targeting the
DATA-STARVED v2 leaves so agents/humans don't wade through 95% benign chatter.

Input : eyenet_messages.jsonl ({"group","text"} from extract_messages.sh)
Output: label_candidates_v2.jsonl ({"group","text","prefilter","hint":[likely leaves]})

Selection = prefilter signals (deface/cred/telecom/tool/access) PLUS keyword probes for
leaves the prefilter has no signal for (infra_resale, recruiting, alliance, crime_aas,
phishing_delivery, fraud_ops). Excludes anything already in the v2 gold (by redacted text).
Balances up to CAP candidates per starved leaf so rare markets actually get coverage.

    .venv/bin/python dataset/sample_candidates.py [CAP_PER_LEAF]
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

import build_dataset as bd
from eyenet.incidents.prefilter import scan

HERE = Path(__file__).parent
SEED = 1337
DEFAULT_CAP = 70  # candidates per starved leaf (filter is noisy; expect ~40-60% true rate)

# Leaves we want more of, and how to spot a candidate. prefilter signals map first;
# keyword probes catch what the prefilter can't express. (?i), ASCII tokens.
SIGNAL_HINT = {
    "deface_banner": "defacement",
    "cred_combo": "credentials", "cred_label": "credentials", "hash_list": "credentials",
    "telecom_abuse": "telecom_abuse",
}
KEYWORDS = {
    "infra_resale": r"(?i)\b(?:bulletproof|bullet\s?proof|vps|rdp|dedicated\s?server|dedi|offshore\s?host|"
                    r"hosting\s?(?:plan|service|panel)|proxies|proxy\s?(?:list|service)|residential\s?prox)\b",
    "recruiting": r"(?i)\b(?:hiring|recruit\w*|we\s?are\s?looking\s?for|join\s?(?:our|the)\s?team|"
                  r"vacanc\w*|apply\s?now|need\s?(?:a\s?)?(?:coder|dev|pentester|spammer|caller))\b",
    "alliance": r"(?i)\b(?:alliance|partnership|joined\s?forces|official\s?partner|team\s?up|"
                r"collaborat\w*|we\s?merge\w*|now\s?allied)\b",
    "crime_aas": r"(?i)\b(?:ransomware|raas|as[-\s]?a[-\s]?service|affiliate\s?program|booter|stress?er)\b",
    "phishing_delivery": r"(?i)\b(?:smtp|sendgrid|web\s?mailer|scam\s?page|scampage|phishing\s?(?:page|kit)|mass\s?mailer)\b",
    "fraud_ops": r"(?i)\b(?:otp\s?bot|cashout|cash\s?out|bank\s?logs?|bank\s?drop|fullz|\bcvv\b|\bdumps?\s?\+?\s?pin\b)\b",
    "crimeware_tooling": r"(?i)\b(?:crypter|fud|keylogger|\brat\b|loader|stealer\s?builder|dd?os\s?script|l7\s?script|dstat)\b",
}
KW = {k: re.compile(v) for k, v in KEYWORDS.items()}


def gold_texts() -> set[str]:
    seen: set[str] = set()
    for f in ("gold_remapped_v2.mllabels.jsonl", "agent_labels_all.mllabels.mllabels.jsonl"):
        p = HERE / f
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    seen.add(bd.redact(json.loads(line)["text"]))
    return seen


def main(cap: int) -> None:
    rng = random.Random(SEED)
    already = gold_texts()
    by_text: dict[str, dict] = {}
    for line in (HERE / "eyenet_messages.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        t = r.get("text", "")
        if not t.strip():
            continue
        by_text[bd.redact(t)] = r  # dedup by redacted text (matches gold keying)

    pools: dict[str, list[dict]] = defaultdict(list)
    for red, r in by_text.items():
        if red in already:
            continue
        text = r["text"]
        sigs = list(scan(text).signals)
        hints: set[str] = {SIGNAL_HINT[s] for s in sigs if s in SIGNAL_HINT}
        if "tool_sale" in sigs:
            hints |= {"crimeware_tooling", "crime_aas"}
        if "access_material" in sigs:
            hints |= {"iab_corporate", "infra_resale", "phishing_delivery"}
        for leaf, rx in KW.items():
            if rx.search(text):
                hints.add(leaf)
        if not hints:
            continue
        cand = {"group": r.get("group"), "text": text, "prefilter": sigs, "hint": sorted(hints)}
        for h in hints:
            pools[h].append(cand)

    # Balanced sample: up to `cap` per starved leaf, deduped across leaves by text.
    chosen: dict[str, dict] = {}
    for leaf in list(KW) + ["defacement", "credentials", "telecom_abuse"]:
        pool = pools.get(leaf, [])
        rng.shuffle(pool)
        for c in pool[:cap]:
            chosen.setdefault(c["text"], c)

    out = list(chosen.values())
    rng.shuffle(out)
    (HERE / "label_candidates_v2.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in out) + "\n", encoding="utf-8"
    )
    print(f"corpus unique (non-gold): {len(by_text) - len(already & set(by_text))}")
    print(f"candidate pool sizes (pre-cap, per targeted leaf):")
    for leaf in sorted(pools, key=lambda k: -len(pools[k])):
        print(f"   {leaf:<18} {len(pools[leaf])}")
    print(f"=== sampled {len(out)} unique candidates (cap {cap}/leaf) -> label_candidates_v2.jsonl ===")


if __name__ == "__main__":
    cap = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else DEFAULT_CAP
    main(cap)
