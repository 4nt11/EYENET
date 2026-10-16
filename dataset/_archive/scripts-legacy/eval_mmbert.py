#!/usr/bin/env python3
"""How does the fine-tuned mmBERT hold on REAL data? Per-case predictions on the
held-out real test (never trained) + redacted benign negatives. Shows where it
fails so we know what synthetic to make harder."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ["USE_TF"] = "0"
import torch  # noqa: E402
from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402

import build_dataset as bd  # noqa: E402
import laya_eval as le  # noqa: E402

HERE = Path(__file__).parent
MODEL = str(HERE / "mmbert-incident")


def main() -> None:
    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(dev).eval()

    pos = [(r["text"], 1) for r in (json.loads(x) for x in (HERE / "test.jsonl").read_text().splitlines())]
    neg = [(bd.redact(t), 0) for t in le.negatives]
    cases = pos + neg

    @torch.no_grad()
    def score(t: str) -> float:
        x = tok(t, return_tensors="pt", truncation=True, max_length=128).to(dev)
        return torch.softmax(model(**x).logits, -1)[0, 1].item()

    rows = [(t, y, score(t)) for t, y in cases]
    rows.sort(key=lambda r: -r[2])
    print("P(inc)  y  ok  text")
    err = 0
    for t, y, p in rows:
        pred = int(p >= 0.5)
        ok = "✓" if pred == y else "✗"
        if pred != y:
            err += 1
        print(f" {p:.2f}   {y}  {ok}  {t[:66].replace(chr(10),' ')}")
    print(f"\n{len(rows)-err}/{len(rows)} correct @0.5; errors={err}")
    # confident errors = the informative ones
    conf_err = [(t, y, p) for t, y, p in rows if int(p >= 0.5) != y and abs(p - 0.5) > 0.3]
    if conf_err:
        print("\nCONFIDENT MISTAKES (what to teach with harder data):")
        for t, y, p in conf_err:
            print(f"  wanted {y}, said {p:.2f}: {t[:70].replace(chr(10),' ')}")


if __name__ == "__main__":
    main()
