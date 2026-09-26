#!/usr/bin/env python3
"""Silver multi-label bootstrap: map prefilter signal families onto the taxonomy
(development/incident-taxonomy.md) so labeling starts as CONFIRM/CORRECT, not create.

Each message gets pre-set 0/1 per label from which prefilter signals fired. Load the
output in labeler.html: silver tags pre-fill the toggles; Enter confirms, 1-5 correct.

`actor_ops` has no reliable structural cue (it's semantic) -> always 0 in silver;
that's the one you'll set by hand. The sale/leak boundary is also human-refined.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from eyenet.incidents.prefilter import scan

HERE = Path(__file__).parent
LABELS = ["incident", "leak", "infostealer", "access_sale", "actor_ops", "tooling"]

# prefilter signal -> label. Only high-confidence mappings; weak/ambiguous signals
# (institutional_target, tg_target, record_count, etc.) set nothing -> human decides.
SIG2LABEL = {
    "deface_banner": "incident", "ddos_command": "incident", "check_host": "incident",
    "compromise_confirmed": "incident", "multi_target": "incident",
    "leak_host": "leak", "leak_label": "leak", "target_dump_file": "leak",
    "pii_schema": "leak", "hash_list": "leak", "cred_combo": "leak",
    "cred_label": "leak", "onion_url": "leak",
    "stealer_logs": "infostealer", "cloud_pass": "infostealer",
    "access_material": "access_sale",
    # NOTE: `sale_marker` deliberately maps to NOTHING. It's a paid-vs-free modifier
    # ("for sale", "escrow", "WTB") that fires on cred/log/ddos-script sales and
    # chatter, none of which is IAB access. It was mislabeling ~165 rows as
    # access_sale. IAB access-sale is thin-to-absent in this corpus (no IAB channels
    # monitored) — hand-label the ~74 access_material (webshell/root) fires instead.
}


def main() -> None:
    # Read the raw corpus and run the pure-RE2 prefilter inline. No GPU / laya /
    # mmBERT needed to bootstrap silver — that model pass (decision_log.py) is only
    # for the auditable per-message score log, not for labeling prep.
    src = HERE / "eyenet_messages.jsonl"
    if not src.exists():  # fall back to a prior decision_log if messages weren't re-extracted
        src = HERE / "decision_log.jsonl"
    rows = [json.loads(x) for x in src.read_text(encoding="utf-8").splitlines() if x.strip()]
    counts = Counter()
    with (HERE / "silver_multilabel.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            signals = r.get("prefilter") if "prefilter" in r else list(scan(r["text"]).signals)
            lab = dict.fromkeys(LABELS, 0)
            for s in signals:
                t = SIG2LABEL.get(s)
                if t:
                    lab[t] = 1
            out = {"group": r.get("group"), "text": r["text"],
                   "prefilter": signals, "mmbert_p": r.get("mmbert_p")}
            out.update(lab)
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
            fired = [k for k in LABELS if lab[k]]
            counts["none" if not fired else "labeled"] += 1
            for k in fired:
                counts[k] += 1
    n = len(rows)
    print(f"silver-tagged {n} -> silver_multilabel.jsonl")
    print(f"  none (no silver label): {counts['none']} ({100*counts['none']//n}%)")
    for k in LABELS:
        print(f"  {k:<12}: {counts[k]}")
    print("  (actor_ops + tooling are 0 in silver by design — no prefilter signal, set by hand)")


if __name__ == "__main__":
    main()
