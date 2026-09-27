#!/usr/bin/env python3
"""Targeted top-up sample for the weak/stillborn heads: tooling, access_sale, actor_ops.

High-recall keyword candidates from the sales-dense channels, EXCLUDING every text
already labeled in *.mllabels.jsonl. Rows keep silver columns so labeler.html pre-fills
what silver knows (access_material -> access_sale); tooling/actor_ops start empty (you
toggle 6 / 5). Output: dataset/topup_sample.jsonl -> load in labeler.html.
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
LABELS = ["incident", "leak", "infostealer", "access_sale", "actor_ops", "tooling"]
SEED = 77
# Round 4 (market): confirm the new tooling/access silver from the 21k market + more actor_ops.
QUOTA = {"tooling": 50, "access_sale": 45, "actor_ops": 30}
OUTFILE = "market_sample.jsonl"

# access to a (usually named) target: shell/cpanel/rdp/vpn/smtp + a sale/offer cue.
RE_ACCESS = re.compile(r"(?i)(?=.*\b(web ?shell|shell|cpanel|c-?panel|rdp|vpn|smtp|akses|acces|access|login)\b)"
                       r"(?=.*\b(for sale|sell|selling|wts|wtb|jual|beli|buy|price|\$\d|dm|pv|contact)\b)")
# reusable tool/service SALE (no specific victim).
RE_TOOL = re.compile(r"(?i)(?=.*\b(ddos|booter|stress(?:er|ing)?|dstat|l7|cnc|rat|malware|loader|"
                     r"builder|checker|combo|cracked?|worm(?:gpt)?|exploit|panel|method|tool|service|course|"
                     r"ajarin|kelas|class)\b)"
                     r"(?=.*\b(for sale|sell|selling|wts|jual|price|\$\d|promo|offering|buy|purchase|contact|service drop)\b)")
RE_ACTOR = re.compile(r"(?i)\b(announc\w*|recruit\w*|open recruitment|join us|alliance|we will|we are|"
                      r"upcoming|coming soon|manifesto|call to action|official (?:channel|alliance|announcement)|"
                      r"new leader|next round|prepared|deploy\w*)\b")
RE_ATTACK_CMD = re.compile(r"(?i)(?:^|\s)/(?:attack|ddos|flood|scan)\b|check-host\.net")
# leak = distribution of stolen data (dumps/dox/DBs/records). High recall; you correct.
RE_LEAK = re.compile(r"(?i)\b(dump|leaked?|dox|database|\bdb\b|records?|breach(?:ed|forums)?|"
                     r"combo\s?list|\.sql|\.csv|citizens?|personal data|dehashed|download|"
                     r"stolen|full[zx]|fullz|data (?:of|for|leak|breach)|[0-9]{2,}k\b)")


def main() -> None:
    rng = random.Random(SEED)
    rows = [json.loads(x) for x in (HERE / "silver_multilabel.jsonl").read_text("utf-8").splitlines() if x.strip()]

    labeled: set[str] = set()
    for gp in HERE.glob("*.mllabels.jsonl"):
        for line in gp.read_text("utf-8").splitlines():
            if line.strip():
                labeled.add(json.loads(line)["text"])

    # dedup available rows by text, drop already-labeled
    avail: dict[str, dict] = {}
    for r in rows:
        t = r["text"]
        if t in labeled or t in avail:
            continue
        avail[t] = r
    pool = list(avail.values())
    rng.shuffle(pool)

    picked: list[dict] = []
    chosen: set[str] = set()

    def take(pred, n):  # pred takes the ROW dict
        got = 0
        for r in pool:
            if got >= n:
                break
            if r["text"] in chosen:
                continue
            if pred(r):
                picked.append(r)
                chosen.add(r["text"])
                got += 1
        return got

    # tooling/access_sale: confirm the actual SILVER fires (high-yield + precision check).
    # actor_ops is silver-blind -> keyword-surface candidates.
    n_t = take(lambda r: bool(r.get("tooling")), QUOTA["tooling"])
    n_a = take(lambda r: bool(r.get("access_sale")), QUOTA["access_sale"])
    n_o = take(lambda r: bool(RE_ACTOR.search(r["text"])) and not RE_ATTACK_CMD.search(r["text"]), QUOTA["actor_ops"])

    rng.shuffle(picked)
    out = HERE / OUTFILE
    with out.open("w", encoding="utf-8") as f:
        for r in picked:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    grp = Counter(r.get("group") for r in picked)
    print(f"{len(picked)} rows -> {out.name}  (tooling≈{n_t} access≈{n_a} actor≈{n_o}, overlap dedup'd)")
    print("per group:", dict(grp.most_common()))
    print("CANDIDATES — confirm/reject. tooling=reusable tool/service sale; access_sale=access to a NAMED target; actor_ops=intent/plans/org.")


if __name__ == "__main__":
    main()
