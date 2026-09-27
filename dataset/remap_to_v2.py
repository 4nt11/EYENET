#!/usr/bin/env python3
"""Remap existing gold from the flat 6 heads to the v2 hierarchical leaf set, and triage
the rows that need human re-inspection.

See development/incident-taxonomy-hierarchy.md. Three old heads (incident, access_sale,
tooling) SPLIT into finer leaves and cannot be mapped mechanically; the rest are 1:1.

Outputs (next to this file):
  - gold_remapped_v2.mllabels.jsonl : rows fully resolved by mechanical rename (ready gold)
  - relabel_queue_v2.jsonl          : rows needing a human split decision (feed to labeler.html)

Re-runnable. Prints the labeling burden so we size the work before doing it.

    .venv/bin/python dataset/remap_to_v2.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import build_dataset as bd  # redact (same keying as the trainer)
from eyenet.incidents.prefilter import scan  # context hints for the labeler

HERE = Path(__file__).parent
OLD_HEADS = ["incident", "leak", "infostealer", "access_sale", "actor_ops", "tooling"]

# 1:1 renames (business model unchanged, just finer name / grouping).
MECHANICAL = {"leak": "breach_dump", "infostealer": "stealer_logs", "actor_ops": "crew_ops"}
# These SPLIT into multiple leaves -> a human must pick which. (See the taxonomy doc.)
SPLIT = {
    "incident": ["defacement", "ddos_attack", "intrusion"],
    "access_sale": ["iab_corporate", "telecom_abuse", "phishing_delivery", "fraud_ops"],
    "tooling": ["crimeware_tooling", "crime_aas"],
}

OUT_GOLD = HERE / "gold_remapped_v2.mllabels.jsonl"
OUT_QUEUE = HERE / "relabel_queue_v2.jsonl"


def old_labels(row: dict) -> set[str]:
    """The set of old heads that are positive on a row (accepts list / dict / flat cols)."""
    lab = row.get("labels")
    if isinstance(lab, list):
        return {x for x in lab if x in OLD_HEADS}
    if isinstance(lab, dict):
        return {k for k in OLD_HEADS if lab.get(k)}
    return {k for k in OLD_HEADS if row.get(k)}


def load_gold_rows() -> list[dict]:
    """All *.mllabels.jsonl rows (skip our own outputs), deduped by redacted text (last wins)."""
    skip = {OUT_GOLD.name, OUT_QUEUE.name}
    by_text: dict[str, dict] = {}
    for gp in sorted(HERE.glob("*.mllabels.jsonl")):
        if gp.name in skip:
            continue
        for line in gp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if isinstance(r.get("text"), str) and r["text"].strip():
                by_text[bd.redact(r["text"])] = r
    return list(by_text.values())


def main() -> None:
    rows = load_gold_rows()
    gold_out: list[str] = []
    queue_out: list[str] = []
    split_counter: Counter[str] = Counter()
    n_clean = n_none = n_review = 0

    for r in rows:
        old = old_labels(r)
        mech = sorted({MECHANICAL[x] for x in old if x in MECHANICAL})
        splits = sorted(old & SPLIT.keys())

        if splits:
            n_review += 1
            for s in splits:
                split_counter[s] += 1
            queue_out.append(
                json.dumps(
                    {
                        "text": r["text"],
                        "group": r.get("group"),
                        "prefilter": list(scan(r["text"]).signals),
                        "old": sorted(old),
                        "seed": mech,  # mechanical leaves already resolved (pre-check these)
                        "decide": splits,  # old heads whose leaf the human must pick
                        "options": sorted({leaf for s in splits for leaf in SPLIT[s]}),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            if old:
                n_clean += 1
            else:
                n_none += 1
            gold_out.append(
                json.dumps({"text": r["text"], "group": r.get("group"), "labels": mech},
                           ensure_ascii=False)
            )

    OUT_GOLD.write_text("\n".join(gold_out) + ("\n" if gold_out else ""), encoding="utf-8")
    OUT_QUEUE.write_text("\n".join(queue_out) + ("\n" if queue_out else ""), encoding="utf-8")

    print(f"total unique gold rows : {len(rows)}")
    print(f"  mechanical (ready)   : {n_clean} positive + {n_none} none  -> {OUT_GOLD.name}")
    print(f"  needs human review   : {n_review}  -> {OUT_QUEUE.name}")
    print("  review breakdown (by old head that splits):")
    for h in ("incident", "access_sale", "tooling"):
        print(f"    {h:<12} {split_counter[h]:>4}  -> one of {SPLIT[h]}")


def _selfcheck() -> None:
    assert old_labels({"labels": ["leak", "tooling"]}) == {"leak", "tooling"}
    assert old_labels({"incident": 1, "leak": 0}) == {"incident"}
    assert sorted({MECHANICAL[x] for x in {"leak", "infostealer"}}) == ["breach_dump", "stealer_logs"]
    print("selfcheck ok")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(HERE))
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()
