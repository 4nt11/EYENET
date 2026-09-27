#!/usr/bin/env python3
"""Full per-message decision log on the real corpus, so decisions are AUDITABLE
instead of just an aggregate number.

For every message writes: group, prefilter signals + adjudicate, laya P, fine-tuned
mmBERT P, and the text. Output -> dataset/decision_log.jsonl (open/grep/jq it).
Only per-channel aggregates print to stdout; raw bodies stay in the file.

mmBERT is the checkpoint we fine-tuned on hard negatives (dataset/mmbert-incident).
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

os.environ["USE_TF"] = "0"
sys.path.insert(0, str(Path(__file__).parent))
import torch  # noqa: E402
from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402

import poc_cascade as pc  # noqa: E402  (scan, QUESTION)

HERE = Path(__file__).parent
MMBERT = str(HERE / "mmbert-incident")
OUT = HERE / "decision_log.jsonl"
DEV = "cuda" if torch.cuda.is_available() else "cpu"


def mmbert_scores(texts: list[str], tok, model, bs: int = 64) -> list[float]:
    out: list[float] = []
    for i in range(0, len(texts), bs):
        chunk = texts[i:i + bs]
        x = tok(chunk, return_tensors="pt", truncation=True, max_length=128, padding=True).to(DEV)
        with torch.no_grad():
            p = torch.softmax(model(**x).logits, -1)[:, 1]
        out.extend(p.tolist())
        print(f"  mmbert {min(i+bs,len(texts))}/{len(texts)}", file=sys.stderr)
    return out


def main() -> None:
    from laya import Router  # noqa: PLC0415

    rows = [json.loads(x) for x in (HERE / "eyenet_messages.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    texts = [r["text"] for r in rows]

    tok = AutoTokenizer.from_pretrained(MMBERT)
    model = AutoModelForSequenceClassification.from_pretrained(MMBERT).to(DEV).eval()
    mm = mmbert_scores(texts, tok, model)

    router = Router(preload=True)
    print("scoring laya + prefilter...", file=sys.stderr)

    ch = defaultdict(lambda: defaultdict(int))
    with open(OUT, "w", encoding="utf-8") as f:
        for i, r in enumerate(rows):
            t, g = r["text"], r["group"]
            pf = pc.scan(t)
            lp = float(router.predict(t, pc.QUESTION)["answers"]["incident"]["probabilities"]["A"])
            rec = {"group": g, "prefilter": list(pf.signals), "pf_adjudicate": pf.adjudicate,
                   "laya_p": round(lp, 3), "mmbert_p": round(mm[i], 3), "text": t}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            ch[g]["n"] += 1
            ch[g]["pf"] += pf.adjudicate
            ch[g]["laya"] += lp >= 0.5
            ch[g]["mmbert"] += mm[i] >= 0.5
            if (i + 1) % 1000 == 0:
                print(f"  ...{i+1}/{len(rows)}", file=sys.stderr)

    print(f"\nwrote {len(rows)} decisions -> {OUT}\n")
    print(f"{'channel':<26} {'n':>5} {'pf%':>4} {'laya%':>6} {'mmbert%':>8}")
    for g, d in sorted(ch.items(), key=lambda kv: -kv[1]["n"]):
        n = d["n"]
        print(f"{g[:26]:<26} {n:>5} {100*d['pf']//n:>3}% {100*d['laya']//n:>5}% {100*d['mmbert']//n:>7}%")
    n = sum(d["n"] for d in ch.values())
    pf = sum(d["pf"] for d in ch.values())
    la = sum(d["laya"] for d in ch.values())
    mb = sum(d["mmbert"] for d in ch.values())
    print(f"\nTOTAL n={n} | prefilter {100*pf//n}% | laya>=.5 {100*la//n}% | mmbert>=.5 {100*mb//n}%")


if __name__ == "__main__":
    main()
