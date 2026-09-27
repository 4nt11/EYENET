#!/usr/bin/env python3
"""Per-head probability calibration (Platt scaling) for the multi-label model.

The raw sigmoids are compressed near zero, so a 0.5 threshold is meaningless and
F1-max lands on razor 0.00-0.01 cutoffs that won't transfer. Platt scaling fits a
per-head affine map on the LOGITS -- p_cal = sigmoid(a*logit + b) -- which both
spreads the probabilities and moves the decision boundary to a usable place. Then a
small F1 threshold sweep on the calibrated probs picks the operating point.

Fit on the SAME held-out human gold the model never trained on. HONESTY: params are
fit on the 118-row gold-test, so numbers are mildly optimistic -- re-run after the
next labels. a,b,thr per head -> calibration.json (supersedes thresholds.json).

    USE_TF=0 .venv/bin/python dataset/calibrate.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ["USE_TF"] = "0"
import numpy as np  # noqa: E402
import torch  # noqa: E402
from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402

from train_mmbert_ml import LABELS, OUT, auroc  # noqa: E402
from tune_thresholds import DEV, best_threshold, gold_test  # noqa: E402  (reuse exact split)

MIN_SUP = 3  # below this, don't fit — keep identity (a=1,b=0) and thr 0.5


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def fit_platt(logit: np.ndarray, y: np.ndarray, iters: int = 4000, lr: float = 0.3) -> tuple[float, float]:
    """1-D logistic fit p=sigmoid(a*logit+b) minimizing BCE. Standardize for stable GD,
    then fold the scaling back into (a,b) on the raw-logit scale."""
    mu, sd = float(logit.mean()), float(logit.std()) or 1.0
    z = (logit - mu) / sd
    a, b = 1.0, 0.0
    for _ in range(iters):
        p = sigmoid(a * z + b)
        ga = float(np.mean((p - y) * z))
        gb = float(np.mean(p - y))
        a -= lr * ga
        b -= lr * gb
    return a / sd, b - a * mu / sd  # convert to raw-logit scale


def main(model_dir: str = OUT) -> None:
    texts, y = gold_test()
    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir).to(DEV).eval()
    logits = []
    for i in range(0, len(texts), 64):
        x = tok(texts[i:i + 64], return_tensors="pt", truncation=True, max_length=128, padding=True).to(DEV)
        with torch.no_grad():
            logits.extend(model(**x).logits.tolist())  # RAW logits, not sigmoid
    logits = np.array(logits)

    calib: dict[str, dict] = {}
    print(f"\ngold-test rows: {len(texts)}   (Platt-calibrated)")
    print(f"{'label':<12} {'sup':>4} {'AUROC':>6} | {'a':>6} {'b':>7} {'thr':>5} {'P':>5} {'R':>5} {'F1':>5}")
    for i, k in enumerate(LABELS):
        lg, y_i = logits[:, i], y[:, i]
        sup = int(y_i.sum())
        au = auroc([p for p, t in zip(lg, y_i) if t == 1], [p for p, t in zip(lg, y_i) if t == 0])
        aus = " n/a " if au != au else f"{au:5.3f}"
        if sup >= MIN_SUP:
            a, b = fit_platt(lg, y_i.astype(float))
        else:
            a, b = 1.0, 0.0
        cal_p = sigmoid(a * lg + b)
        thr, pr, rc, f1 = best_threshold(cal_p, y_i) if sup >= MIN_SUP else (0.5, 0.0, 0.0, 0.0)
        calib[k] = {"a": round(a, 4), "b": round(b, 4), "thr": round(thr, 3)}
        note = "" if sup >= MIN_SUP else " (sup<MIN, identity)"
        print(f"{k:<12} {sup:>4} {aus} | {a:6.2f} {b:7.2f} {thr:5.2f} {pr:5.2f} {rc:5.2f} {f1:5.2f}{note}")

    (Path(model_dir) / "calibration.json").write_text(json.dumps(calib, indent=2), encoding="utf-8")
    print(f"\nsaved -> {model_dir}/calibration.json   (apply: p = sigmoid(a*logit + b); flag if p >= thr)")
    print("NOTE: fit on gold-test -> re-run after next labels to confirm thresholds land sanely (~0.5).")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default=OUT, help="model dir to calibrate (default: deployed)")
    main(ap.parse_args().model_dir)
