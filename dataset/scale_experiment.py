#!/usr/bin/env python3
"""Scale test of the incident cascade on the real EYENET corpus (8264 msgs).

All messages are threat-actor traffic (hasanbroker et al.), so the question is
NOT "benign vs malicious channel" — it's: does the cascade fire on incident
DECLARATIONS (dumps/brags/sales/DDoS) and stay quiet on criminals chatting/
negotiating? Reports AGGREGATE per-channel rates only — no raw bodies echoed.

prefilter + laya run on all messages (fast). qwen runs on a capped random sample
of the uncertain band to gauge stage-3 behavior without an hours-long sequential run.
"""

from __future__ import annotations

import json
import os
import random
import sys
from collections import defaultdict
from pathlib import Path

os.environ["USE_TF"] = "0"
sys.path.insert(0, str(Path(__file__).parent))
import poc_cascade as pc  # noqa: E402  (reuse scan, QUESTION, llm_judge, HIGH/LOW)

HERE = Path(__file__).parent
QWEN_SAMPLE_CAP = 150


def main() -> None:
    from laya import Router  # noqa: PLC0415

    rows = [json.loads(x) for x in (HERE / "eyenet_messages.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    router = Router(preload=True)
    print(f"loaded {len(rows)} messages; running prefilter + laya...", file=sys.stderr)

    # per-channel counters
    ch: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    uncertain: list[tuple[str, str, tuple[str, ...], float]] = []
    for i, r in enumerate(rows):
        t = r["text"]
        g = r["group"]
        pf = pc.scan(t)
        p = float(router.predict(t, pc.QUESTION)["answers"]["incident"]["probabilities"]["A"])
        ch[g]["n"] += 1
        if pf.adjudicate:
            ch[g]["prefilter"] += 1
        flag2 = pf.adjudicate or p >= 0.5           # 2-stage decision
        ch[g]["flagged2"] += flag2
        if (pc.LOW < p < pc.HIGH) or (pf.adjudicate and p < pc.LOW):
            ch[g]["uncertain"] += 1
            uncertain.append((g, t, pf.signals, p))
        if (i + 1) % 1000 == 0:
            print(f"  ...{i + 1}/{len(rows)}", file=sys.stderr)

    print("\n=== per-channel (2-stage: prefilter OR laya>=0.5) ===")
    print(f"{'channel':<28} {'n':>5} {'flag':>6} {'flag%':>6} {'unsure%':>7}")
    for g, d in sorted(ch.items(), key=lambda kv: -kv[1]["n"]):
        n = d["n"]
        print(f"{g[:28]:<28} {n:>5} {d['flagged2']:>6} {100*d['flagged2']//n:>5}% {100*d['uncertain']//n:>6}%")
    tot = sum(d["n"] for d in ch.values())
    fl = sum(d["flagged2"] for d in ch.values())
    un = sum(d["uncertain"] for d in ch.values())
    print(f"\nTOTAL {fl}/{tot} flagged ({100*fl//tot}%); {un} in uncertain band ({100*un//tot}% -> would hit qwen)")

    # qwen on a random sample of the uncertain band
    random.seed(0)
    sample = random.sample(uncertain, min(QWEN_SAMPLE_CAP, len(uncertain)))
    print(f"\n=== qwen on {len(sample)} sampled uncertain msgs ===", file=sys.stderr)
    yes = 0
    for g, t, sig, p in sample:
        inc, _ = pc.llm_judge(t, sig, p)
        yes += inc
    print(f"qwen sample: {yes}/{len(sample)} judged INCIDENT "
          f"({100*yes//max(len(sample),1)}% of the uncertain band)")


if __name__ == "__main__":
    main()
