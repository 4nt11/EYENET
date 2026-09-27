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

from eyenet.incidents.classifier import SIG2LABEL  # canonical signal->label map
from eyenet.incidents.prefilter import scan

HERE = Path(__file__).parent
LABELS = ["incident", "leak", "infostealer", "access_sale", "actor_ops", "tooling"]

# SIG2LABEL is imported from eyenet.incidents.classifier (single source of truth, shared
# with the classifier's prefilter fusion). Only high-confidence mappings live there;
# weak/ambiguous signals (sale_marker, tg_target, record_count, ...) map to nothing so a
# human decides. `sale_marker` deliberately maps to NOTHING (a paid-vs-free modifier that
# was mislabeling ~165 chatter/cred/ddos rows as access_sale).


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
    print("  (actor_ops is 0 in silver by design — semantic, no prefilter signal, set by hand)")


if __name__ == "__main__":
    main()
