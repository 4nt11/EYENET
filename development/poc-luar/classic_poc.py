#!/usr/bin/env python
"""Classical stylometry baselines vs LUAR, on the identical split-half protocol.

Same authors, same early-half(query)/late-half(target) split as luar_poc.py, but
scored with three classic measures instead of a neural embedding:

  * Burrows's Delta  -- z-scored relative frequency of the K most-frequent words,
    Manhattan distance. The classic stylometric workhorse.
  * Jaccard distance -- 1 - |A n B| / |A u B| over character n-gram SETS. Captures
    vocabulary/morphology overlap, position-independent.
  * KL / Jensen-Shannon -- divergence between the two texts' character n-gram
    probability distributions (JS = symmetric, bounded KL).

Each method yields a query x target distance matrix over the same authors, so
R@1 and EER are directly comparable to the LUAR numbers in out/report_*.json.

No GPU, no new deps. Reuses the DB fetch + actor grouping from luar_poc.

Run:  ./.venv/bin/python classic_poc.py --groups both --max-authors 300
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np

from luar_poc import OUT, eer, fetch_baseline, fetch_spanish, group_actors

WORD = re.compile(r"[0-9a-záéíóúüñ]+")
# distinctive_vocabulary primitive's own token rule: words >=3 chars, accents kept
_WORD3 = re.compile(r"[a-záéíóúüñàèìòùâêîôûäëïöü]{3,}", re.IGNORECASE)
_WS = re.compile(r"\s+")


def words3(t: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD3.finditer(t)]


def words(t: str) -> list[str]:
    return WORD.findall(t.lower())


def char_ngrams(t: str, n: int) -> list[str]:
    t = _WS.sub(" ", t.lower())
    return [t[i:i + n] for i in range(len(t) - n + 1)] if len(t) >= n else [t]


# ------------------------------------------------------------------- feature reps

def burrows_z(docs: list[str], k: int = 150) -> np.ndarray:
    """Z-scored relative frequencies of the top-k words, over the doc set."""
    toks = [words(d) for d in docs]
    total: Counter = Counter()
    for t in toks:
        total.update(t)
    mfw = [w for w, _ in total.most_common(k)]
    F = np.zeros((len(docs), len(mfw)))
    for i, t in enumerate(toks):
        c = Counter(t)
        n = len(t) or 1
        for j, w in enumerate(mfw):
            F[i, j] = c[w] / n
    mu, sd = F.mean(0), F.std(0) + 1e-9
    return (F - mu) / sd


def ngram_sets(docs: list[str], n: int = 4) -> list[set]:
    return [set(char_ngrams(d, n)) for d in docs]


def tfidf_rareword(docs: list[str], min_df: int = 2) -> np.ndarray:
    """L2-normalized TF-IDF rare-word vectors over a SHARED (corpus) vocabulary.

    Full-distribution version of EYENET's distinctive_vocabulary_signature, which
    simhashes per-actor TF-IDF top-50 (and admits it is not cross-actor
    comparable). Here IDF is corpus-wide so vectors live in one space; high-IDF
    (rare) words dominate the cosine -- "rare words are where authorial choice
    lives". min_df drops pile-hapax that can never match.
    """
    toks = [words3(d) for d in docs]
    N = len(docs)
    df: Counter = Counter()
    for t in toks:
        df.update(set(t))
    vocab = [w for w, d in df.items() if d >= min_df]
    vi = {w: i for i, w in enumerate(vocab)}
    idf = {w: math.log((N + 1) / (df[w] + 1)) + 1.0 for w in vocab}
    M = np.zeros((N, len(vocab)))
    for i, t in enumerate(toks):
        c = Counter(t)
        tot = sum(c.values()) or 1
        for w, cnt in c.items():
            j = vi.get(w)
            if j is not None:
                M[i, j] = (cnt / tot) * idf[w]
    nrm = np.linalg.norm(M, axis=1, keepdims=True)
    nrm[nrm == 0] = 1.0
    return M / nrm


def cosine_dist(M: np.ndarray, qi, ti) -> np.ndarray:
    return 1.0 - M[qi] @ M[ti].T


def ngram_prob(docs: list[str], n: int = 3, top: int = 1000,
               addk: float = 0.5) -> np.ndarray:
    """Smoothed probability distribution over the top char n-grams."""
    counts = [Counter(char_ngrams(d, n)) for d in docs]
    total: Counter = Counter()
    for c in counts:
        total.update(c)
    vocab = [g for g, _ in total.most_common(top)]
    P = np.zeros((len(docs), len(vocab)))
    for i, c in enumerate(counts):
        row = np.array([c.get(g, 0) for g in vocab], dtype=float) + addk
        P[i] = row / row.sum()
    return P


# ------------------------------------------------------------------- distance mats

def burrows_dist(Z: np.ndarray, qi, ti) -> np.ndarray:
    # mean |z_q - z_t| (Manhattan / n_features)
    return np.abs(Z[qi][:, None, :] - Z[ti][None, :, :]).mean(axis=2)


def jaccard_dist(sets: list[set], qi, ti) -> np.ndarray:
    D = np.zeros((len(qi), len(ti)))
    for a, i in enumerate(qi):
        for b, j in enumerate(ti):
            u = len(sets[i] | sets[j]) or 1
            D[a, b] = 1.0 - len(sets[i] & sets[j]) / u
    return D


def js_dist(P: np.ndarray, qi, ti) -> np.ndarray:
    def kl(p, q):
        return np.sum(p * np.log(p / q), axis=-1)
    D = np.zeros((len(qi), len(ti)))
    for a, i in enumerate(qi):
        p = P[i]
        for b, j in enumerate(ti):
            q = P[j]
            m = 0.5 * (p + q)
            D[a, b] = 0.5 * kl(p, m) + 0.5 * kl(q, m)  # Jensen-Shannon
    return D


# -------------------------------------------------------------------- harness

def _metrics(D: np.ndarray) -> dict:
    """D: query x target DISTANCE (lower = same author). Mirror eval_verification."""
    n = D.shape[0]
    sim = -D  # eer() expects accept-if-score>=t
    same = np.diag(sim)
    diff = sim[~np.eye(n, dtype=bool)]
    return {
        "n_authors": n,
        "r_at_1": round(float((D.argmin(1) == np.arange(n)).mean()), 3),
        "mean_same_dist": round(float(np.diag(D).mean()), 4),
        "mean_diff_dist": round(float(D[~np.eye(n, dtype=bool)].mean()), 4),
        "eer": round(eer(same, diff), 3),
    }


def build_docs(actors, min_msgs, max_authors):
    qual = [a for a in actors.values() if len(a.msgs) >= min_msgs]
    if max_authors:
        qual = qual[:max_authors]
    labels, early, late = [], [], []
    for a in qual:
        mid = len(a.msgs) // 2
        labels.append(a.label)
        early.append(" ".join(a.msgs[:mid]))   # full half, no cap -> more signal
        late.append(" ".join(a.msgs[mid:]))
    return labels, early, late


def run_set(actors, min_msgs, max_authors, tag) -> dict:
    labels, early, late = build_docs(actors, min_msgs, max_authors)
    n = len(labels)
    if n < 2:
        return {"tag": tag, "n_authors": n, "note": "too few authors"}
    docs = early + late                 # 0..n-1 queries, n..2n-1 targets
    qi = np.arange(n)
    ti = np.arange(n, 2 * n)
    Z = burrows_z(docs)
    S4 = ngram_sets(docs, n=4)
    P3 = ngram_prob(docs, n=3)
    return {
        "tag": tag, "n_authors": n,
        "burrows_delta": _metrics(burrows_dist(Z, qi, ti)),
        "jaccard_char4": _metrics(jaccard_dist(S4, qi, ti)),
        "js_char3": _metrics(js_dist(P3, qi, ti)),
    }


def _luar_eer(report_path: Path, key: str) -> str:
    try:
        r = json.loads(report_path.read_text())
        d = r[key]["centered"]
        return f"R@1={d['r_at_1']} EER={d['eer']}"
    except Exception:
        return "(run luar_poc first)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups", choices=["spanish", "baseline", "both"], default="both")
    ap.add_argument("--spanish-min", type=int, default=8)
    ap.add_argument("--baseline-min", type=int, default=40)
    ap.add_argument("--max-authors", type=int, default=300)
    args = ap.parse_args()

    report = {}
    if args.groups in ("spanish", "both"):
        report["spanish"] = run_set(group_actors(fetch_spanish()),
                                    args.spanish_min, 0, "spanish")
    if args.groups in ("baseline", "both"):
        report["baseline"] = run_set(group_actors(fetch_baseline(args.baseline_min)),
                                     args.baseline_min, args.max_authors, "baseline")

    (OUT / "classic.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))

    luar = OUT / "report_LUAR-MUD.json"
    for setname, res in report.items():
        print(f"\n### {setname}  (n_authors={res.get('n_authors', '?')})")
        if "note" in res:
            print(" ", res["note"]); continue
        for method in ("burrows_delta", "jaccard_char4", "js_char3"):
            m = res[method]
            print(f"  {method:16s} R@1={m['r_at_1']:<6} EER={m['eer']:<6} "
                  f"(same_d={m['mean_same_dist']} diff_d={m['mean_diff_dist']})")
        key = "spanish_verification" if setname == "spanish" else "baseline_verification"
        print(f"  {'LUAR-MUD (cent.)':16s} {_luar_eer(luar, key)}")
    print(f"\n[classic-poc] wrote {OUT/'classic.json'}")


if __name__ == "__main__":
    main()
