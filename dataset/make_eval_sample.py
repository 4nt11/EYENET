#!/usr/bin/env python3
"""Pull a RANDOM, BLIND eval sample for unbiased labeling.

Random (not uncertainty-ordered) so the labels give an unbiased accuracy estimate,
and BLIND (no mmbert_p/laya_p fields) so the labeler shows no model hint and you
aren't nudged toward agreeing. Excludes anything already labeled in
decision_log.labels.jsonl. Load eval_sample.jsonl in labeler.html next session.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).parent
N = 250

random.seed(7)
labeled = {json.loads(l)["text"] for l in (HERE / "decision_log.labels.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
rows = [json.loads(l) for l in (HERE / "decision_log.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
pool = [r for r in rows if r["text"] not in labeled]
sample = random.sample(pool, min(N, len(pool)))

with (HERE / "eval_sample.jsonl").open("w", encoding="utf-8") as f:
    for r in sample:  # group + text ONLY — no scores => blind labeling
        f.write(json.dumps({"group": r["group"], "text": r["text"]}, ensure_ascii=False) + "\n")
print(f"wrote {len(sample)} random blind msgs -> eval_sample.jsonl (excludes {len(labeled)} already labeled)")
