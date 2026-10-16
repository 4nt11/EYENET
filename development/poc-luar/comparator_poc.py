#!/usr/bin/env python
"""Prototype of recommendation 1: a calibrated full-distribution comparator.

NOT wired into eyenet. This shows what a replacement for the shipped
simhash-Hamming comparators would look like as an operator-facing verifier:

  * score a cross-context pair with full-distribution features (no 64-bit
    quantization): Burrows (function words) + char-trigram JS,
  * pick a THRESHOLD at a target false-accept rate (FAR), and report the
    recall and precision you actually get there (precision at the matrix base
    rate, which is the honest many-candidates number),
  * test a FREE ensemble (z-score each method's scores, average) to see if
    combining the cheap methods closes the gap to LUAR.

The operating point is the part the bake-off lacked: EER/AUC describe the whole
curve, but an operator runs at ONE threshold and needs to know "if I accept at
FAR 1%, how many real links do I catch, and how many of my accepts are right?"

Run:  ./.venv/bin/python comparator_poc.py --min-msgs 8 --far 0.01
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np

from crosscontext_poc import (OUT, build_persons, fetch_cross_context,
                              fetch_cross_source, sim_burrows, sim_distinctive_vocab,
                              sim_eyenet_char3, sim_eyenet_fnword,
                              sim_full_char3_js, _metrics_from_sim)


def operating_point(S: np.ndarray, target_far: float) -> dict:
    """Threshold at target FAR on the off-diagonal (impostor) scores.

    Reports recall (true-link catch rate) and precision at the matrix base rate
    (positives = n of n^2 cells), which is the realistic skewed-prior number.
    """
    n = S.shape[0]
    same = np.diag(S)
    diff = S[~np.eye(n, dtype=bool)]
    # threshold = the score the impostor distribution exceeds only target_far of the time
    thr = float(np.quantile(diff, 1.0 - target_far))
    tp = int((same >= thr).sum())
    fp = int((diff >= thr).sum())
    recall = tp / n
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    return {
        "target_far": target_far,
        "threshold": round(thr, 4),
        "recall": round(recall, 3),
        "actual_far": round(fp / len(diff), 4),
        "precision_at_base_rate": round(precision, 3),
        "base_rate": round(1.0 / n, 4),
    }


def zscore(S: np.ndarray) -> np.ndarray:
    return (S - S.mean()) / (S.std() + 1e-9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-msgs", type=int, default=10)
    ap.add_argument("--far", type=float, default=0.01, help="target false-accept rate")
    ap.add_argument("--mode", choices=["cross-group", "cross-source"],
                    default="cross-source")
    ap.add_argument("--no-luar", action="store_true")
    args = ap.parse_args()

    rows = (fetch_cross_source(args.min_msgs) if args.mode == "cross-source"
            else fetch_cross_context(args.min_msgs))
    persons = build_persons(rows)
    n = len(persons)
    print(f"[cmp] mode={args.mode}: {n} persons (min {args.min_msgs} msgs/context)")
    if n < 3:
        print("too few persons; lower --min-msgs"); return
    Q = [p["pileA"] for p in persons]
    T = [p["pileB"] for p in persons]

    # build similarity matrices
    mats: dict[str, np.ndarray] = {
        "eyenet_fnword_simhash": sim_eyenet_fnword(Q, T),   # shipped baseline
        "eyenet_char3_simhash": sim_eyenet_char3(Q, T),     # shipped baseline
        "burrows_delta": sim_burrows(Q, T),                 # full fn-words
        "full_char3_js": sim_full_char3_js(Q, T),           # full char-3
        "distinctive_vocab": sim_distinctive_vocab(Q, T),   # full TF-IDF rare words
    }
    if not args.no_luar:
        from crosscontext_poc import sim_luar
        from luar_poc import Embedder
        print("[cmp] loading LUAR ...")
        mats["luar_centered"] = sim_luar(Q, T, Embedder())

    # free ensemble: z-score + average the cheap full-distribution methods
    mats["ENSEMBLE_free (distinct+char3js)"] = (
        zscore(mats["distinctive_vocab"]) + zscore(mats["full_char3_js"])) / 2
    # full ensemble: add LUAR if present
    if "luar_centered" in mats:
        mats["ENSEMBLE_all (+luar)"] = (
            zscore(mats["distinctive_vocab"]) + zscore(mats["full_char3_js"])
            + zscore(mats["luar_centered"])) / 3

    report = {"n": n, "min_msgs": args.min_msgs, "methods": {}}
    print(f"\n{'method':34s} | AUC   EER   | FAR={args.far:>4}: recall  prec@base")
    print("-" * 78)
    for name, S in mats.items():
        m = _metrics_from_sim(S)
        op = operating_point(S, args.far)
        report["methods"][name] = {**m, "operating_point": op}
        print(f"{name:34s} | {m['auc']:<5} {m['eer']:<5} | "
              f"{op['recall']:>6}   {op['precision_at_base_rate']:>6}")

    (OUT / "comparator.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n[cmp] base rate = {report['methods'][list(mats)[0]]['operating_point']['base_rate']} "
          f"(1 real link per {n} candidates)")
    print(f"[cmp] wrote {OUT/'comparator.json'}")


# ponytail: check the operating-point math on a clean separable toy.
def _selfcheck():
    rng = np.random.default_rng(0)
    S = rng.uniform(0.0, 0.3, (10, 10))  # impostors: spread of low scores
    np.fill_diagonal(S, 0.95)            # true links: clearly higher
    op = operating_point(S, 0.1)
    assert op["recall"] == 1.0, op       # all true links above threshold
    assert op["precision_at_base_rate"] > 0.4, op
    assert op["actual_far"] <= 0.15, op
    print("selfcheck ok")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        _selfcheck()
    else:
        main()
