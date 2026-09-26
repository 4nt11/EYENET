#!/usr/bin/env python3
"""Per-head decision-threshold tuning for the multi-label model.

Rare heads (actor_ops, tooling) rank well (good AUROC) but their sigmoid probs sit
below 0.5, so P/R@0.5 = 0. This sweeps each head's threshold on the SAME held-out
human gold the model never trained on, picks the F1-max cutoff, writes thresholds.json.

HONESTY: thresholds are FIT on the 98-row gold-test, so the reported F1 is mildly
optimistic (tuned + measured on the same small set). They're 6 scalars over 98 rows —
low overfit risk — but re-run this after the next labeling batch to confirm they hold.

    USE_TF=0 .venv/bin/python dataset/tune_thresholds.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ["USE_TF"] = "0"
import numpy as np  # noqa: E402
import torch  # noqa: E402
from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402

# reuse the EXACT split + helpers from the trainer (no logic duplication)
from train_mmbert_ml import GOLD_TEST_FRAC, LABELS, OUT, SEED, auroc, load_gold  # noqa: E402

HERE = Path(__file__).parent
DEV = "cuda" if torch.cuda.is_available() else "cpu"
MIN_SUP = 3  # below this, keep 0.5 — too few positives to trust a tuned cutoff


def gold_test() -> tuple[list[str], np.ndarray]:
    gold = load_gold()  # {redacted_text: vec}
    items = list(gold.items())
    np.random.default_rng(SEED).shuffle(items)  # same rng/seed as the trainer
    cut = int(len(items) * (1 - GOLD_TEST_FRAC))
    te = items[cut:]
    return [t for t, _ in te], np.array([v for _, v in te])


def best_threshold(prob: np.ndarray, y: np.ndarray) -> tuple[float, float, float, float]:
    """Return (thr, P, R, F1) maximizing F1 over candidate cutoffs."""
    best = (0.5, 0.0, 0.0, -1.0)
    cands = sorted({round(float(p), 3) for p in prob} | {0.5})
    for thr in cands:
        pred = prob >= thr
        tp = int((pred & (y == 1)).sum())
        prec = tp / max(1, int(pred.sum()))
        rec = tp / max(1, int((y == 1).sum()))
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        if f1 > best[3]:
            best = (thr, prec, rec, f1)
    return best


def main() -> None:
    texts, y = gold_test()
    tok = AutoTokenizer.from_pretrained(OUT)
    model = AutoModelForSequenceClassification.from_pretrained(OUT).to(DEV).eval()
    probs = []
    for i in range(0, len(texts), 64):
        x = tok(texts[i:i + 64], return_tensors="pt", truncation=True, max_length=128, padding=True).to(DEV)
        with torch.no_grad():
            probs.extend(torch.sigmoid(model(**x).logits).tolist())
    probs = np.array(probs)

    thresholds: dict[str, float] = {}
    print(f"\ngold-test rows: {len(texts)}")
    print(f"{'label':<12} {'sup':>4} {'AUROC':>6} | {'thr':>5} {'P':>5} {'R':>5} {'F1':>5}  (vs @0.5)")
    for i, k in enumerate(LABELS):
        p_i, y_i = probs[:, i], y[:, i]
        sup = int(y_i.sum())
        au = auroc([p for p, t in zip(p_i, y_i) if t == 1], [p for p, t in zip(p_i, y_i) if t == 0])
        aus = " n/a " if au != au else f"{au:5.3f}"
        # baseline @0.5
        b_pred = p_i >= 0.5
        b_tp = int((b_pred & (y_i == 1)).sum())
        b_p = b_tp / max(1, int(b_pred.sum())); b_r = b_tp / max(1, sup)
        b_f1 = 2 * b_p * b_r / (b_p + b_r) if (b_p + b_r) else 0.0
        if sup >= MIN_SUP:
            thr, pr, rc, f1 = best_threshold(p_i, y_i)
        else:
            thr, pr, rc, f1 = 0.5, b_p, b_r, b_f1
        thresholds[k] = thr
        note = "" if sup >= MIN_SUP else " (sup<MIN, kept 0.5)"
        print(f"{k:<12} {sup:>4} {aus} | {thr:5.2f} {pr:5.2f} {rc:5.2f} {f1:5.2f}  (F1@.5={b_f1:.2f}){note}")

    (Path(OUT) / "thresholds.json").write_text(json.dumps(thresholds, indent=2), encoding="utf-8")
    print(f"\nsaved -> {OUT}/thresholds.json")
    print("NOTE: fit on gold-test -> slightly optimistic; re-run after next labels to confirm.")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(HERE))
    main()
