#!/usr/bin/env python3
"""Score the FULL corpus with the trained multi-label model and show, per channel,
which heads fire. This is inference on (mostly) training data -> agreement is
circular; the signal we want is whether each head lights up in sensible channels.

Full per-message probs -> decision_log_ml.jsonl (grep/jq it). Only aggregates +
a few top examples per head print to stdout.

    USE_TF=0 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True .venv/bin/python dataset/sweep_ml.py
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

os.environ["USE_TF"] = "0"
import torch  # noqa: E402
from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402

import build_dataset as bd  # noqa: E402  (redact, to match training distribution)

HERE = Path(__file__).parent
MODEL = str(HERE / "mmbert-incident-ml")
CORPUS = HERE / "eyenet_messages.jsonl"
OUT = HERE / "decision_log_ml.jsonl"
DEV = "cuda" if torch.cuda.is_available() else "cpu"
THR = 0.5


def main() -> None:
    labels = json.loads((Path(MODEL) / "labels.json").read_text())
    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL).to(DEV).eval()

    rows = [json.loads(x) for x in CORPUS.read_text("utf-8").splitlines() if x.strip()]
    texts = [bd.redact(r["text"]) for r in rows]

    probs: list[list[float]] = []
    bs = 64
    for i in range(0, len(texts), bs):
        x = tok(texts[i:i + bs], return_tensors="pt", truncation=True, max_length=128, padding=True).to(DEV)
        with torch.no_grad():
            p = torch.sigmoid(model(**x).logits)
        probs.extend(p.tolist())
        print(f"  {min(i + bs, len(texts))}/{len(texts)}", end="\r")
    print()

    # per-channel fire counts + top examples per head
    chan_total: dict[str, int] = defaultdict(int)
    chan_fire: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    top: dict[str, list] = {k: [] for k in labels}
    with OUT.open("w", encoding="utf-8") as f:
        for r, pv in zip(rows, probs):
            g = r.get("group") or "?"
            chan_total[g] += 1
            rec = {"group": g, **{k: round(pv[j], 4) for j, k in enumerate(labels)}, "text": r["text"]}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            for j, k in enumerate(labels):
                if pv[j] >= THR:
                    chan_fire[g][k] += 1
                top[k].append((pv[j], g, " ".join(r["text"].split())[:70]))

    heads = labels
    w = max(len(g) for g in chan_total) + 1
    print("\nper-channel fire rate (% of channel msgs >= 0.5):")
    print(" " * w + "  " + "  ".join(f"{k[:7]:>7}" for k in heads) + f"   {'msgs':>6}")
    for g in sorted(chan_total, key=lambda x: -chan_total[x]):
        n = chan_total[g]
        cells = "  ".join(f"{100 * chan_fire[g][k] // n:>6}%" for k in heads)
        print(f"{g:<{w}}  {cells}   {n:>6}")

    print("\ntotal msgs flagged per head:")
    for k in heads:
        print(f"  {k:<12}: {sum(chan_fire[g][k] for g in chan_total)}")

    print("\ntop-3 highest-prob per head (prob | channel | text):")
    for k in heads:
        print(f"  --- {k} ---")
        for p, g, t in sorted(top[k], reverse=True)[:3]:
            print(f"    {p:.2f} [{g[:14]}] {t}")
    print(f"\nfull per-msg probs -> {OUT.name}")


if __name__ == "__main__":
    main()
