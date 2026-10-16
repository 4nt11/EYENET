#!/usr/bin/env python
"""LUAR authorship-representation PoC against the live EYENET corpus.

Three evals, all sharing one LUAR embedder:

  A. Verification (split-half): for every actor with enough text, split their
     messages temporally (early half = query, late half = target), embed each
     half as a LUAR "episode", and ask whether the same author's two halves are
     nearest neighbours. Reports R@1, same-vs-diff cosine, and EER. This is the
     standard authorship-verification protocol and yields a real number even on
     a modest author count (it just gets noisier the fewer authors there are).

  B. Spanish heatmap: the soulhem/mortem/pampa actors specifically, rendered as
     a query x target cosine heatmap so you can eyeball same-author lighting up.

  C. Within-channel operator discovery (EXPLORATORY, no ground truth): for each
     broadcast CHANNEL, chunk posts chronologically into episodes, embed each,
     and cluster. "Does this channel read like one hand or several?" We have no
     post_author labels on this backfilled data, so this is a hypothesis
     generator, not a verified result.

DB access is via `docker exec docker-postgres-1 psql ... COPY ... TO STDOUT CSV`
because Postgres is not port-mapped to the host (docker-internal only). No host
networking, no psycopg connection string juggling.

Run:  ./.venv/bin/python luar_poc.py --groups spanish
      ./.venv/bin/python luar_poc.py --groups both --baseline-min 40
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

csv.field_size_limit(1 << 27)  # forum posts can embed huge pasted dumps (>128KB default)

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

PG_CONTAINER = "docker-postgres-1"
PG_USER = "eyenet"
PG_DB = "eyenet"
PG_PASSWORD = "b7c4bb3a527ff8cbbd0b6d432a664e8078f4cb18d570e80c"  # local dev DB; not a secret worth hiding from a PoC in the same repo

SPANISH_TITLE_PATTERNS = ["%soulhem%", "%mortem%", "%pampa%"]

MODEL_NAME = "rrivera1849/LUAR-MUD"
MAX_TOKENS = 64          # per-post token cap (HF example uses 32; chat msgs run longer)
EPISODE_POSTS = 32       # max posts folded into one author episode


# --------------------------------------------------------------------------- DB

def pg_csv(sql: str) -> list[dict]:
    """Run a SELECT via docker exec psql COPY ... TO STDOUT CSV, parse to dicts.

    COPY CSV handles embedded newlines/commas/quotes in message bodies correctly,
    which a naive -F'|' dump does not.
    """
    copy = f"COPY ({sql}) TO STDOUT WITH (FORMAT csv, HEADER true)"
    proc = subprocess.run(
        ["docker", "exec", "-e", f"PGPASSWORD={PG_PASSWORD}", PG_CONTAINER,
         "psql", "-U", PG_USER, "-d", PG_DB, "-c", copy],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"psql failed:\n{proc.stderr}")
    return list(csv.DictReader(io.StringIO(proc.stdout)))


# usable = real text, not flagged copypasta
_USABLE = ("m.length_words >= 5 "
           "AND coalesce(c.is_copypasta, false) = false "
           "AND m.body IS NOT NULL AND length(trim(m.body)) > 0")

_SELECT_COLS = (
    "m.actor_id, "
    "coalesce(nullif(a.current_handle,''), nullif(a.current_display_name,''), "
    "  left(m.actor_id::text,8)) AS label, "
    "g.current_title AS group_title, g.kind::text AS group_kind, "
    "m.sent_at_source AS sent_at, m.body"
)
_FROM = ("message m "
         "LEFT JOIN content_template c ON m.template_id = c.id "
         "JOIN group_ g ON m.group_id = g.id "
         "JOIN actor a ON m.actor_id = a.id")


def fetch_spanish() -> list[dict]:
    like = " OR ".join(f"g.current_title ILIKE '{p}'" for p in SPANISH_TITLE_PATTERNS)
    sql = (f"SELECT {_SELECT_COLS} FROM {_FROM} "
           f"WHERE ({like}) AND {_USABLE} ORDER BY m.actor_id, m.sent_at_source")
    return pg_csv(sql)


def fetch_baseline(min_msgs: int, cap_per_actor: int = 120) -> list[dict]:
    """Deep actors from CHAT groups corpus-wide, for a less-noisy verification
    number. Capped per actor so one chatterbox can't dominate."""
    sql = (
        f"SELECT * FROM ("
        f"  SELECT {_SELECT_COLS}, "
        f"    count(*) OVER (PARTITION BY m.actor_id) AS n_actor, "
        f"    row_number() OVER (PARTITION BY m.actor_id ORDER BY m.sent_at_source) AS rn "
        f"  FROM {_FROM} "
        f"  WHERE g.kind = 'CHAT' AND {_USABLE}"
        f") s WHERE s.n_actor >= {min_msgs} AND s.rn <= {cap_per_actor} "
        f"ORDER BY actor_id, sent_at"
    )
    return pg_csv(sql)


# ------------------------------------------------------------------------- model

class Embedder:
    def __init__(self, model_name: str = MODEL_NAME):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name, trust_remote_code=True).eval()
        self.dev = "cuda" if torch.cuda.is_available() else "cpu"
        self.model.to(self.dev)

    def embed(self, posts: list[str]) -> np.ndarray:
        """One author episode -> L2-normalized 512-d vector."""
        if not posts:
            raise ValueError("empty episode")
        t = self.tok(posts, max_length=MAX_TOKENS, padding="max_length",
                     truncation=True, return_tensors="pt")
        ids = t["input_ids"].reshape(1, len(posts), -1).to(self.dev)
        am = t["attention_mask"].reshape(1, len(posts), -1).to(self.dev)
        with self.torch.no_grad():
            out = self.model(input_ids=ids, attention_mask=am)
        v = out.detach().cpu().numpy()[0].astype(np.float64)
        n = np.linalg.norm(v)
        return v / n if n else v


def _sample(items: list, k: int) -> list:
    """Evenly subsample to at most k, preserving order."""
    if len(items) <= k:
        return items
    idx = np.linspace(0, len(items) - 1, k).round().astype(int)
    return [items[i] for i in idx]


# -------------------------------------------------------------------------- data

@dataclass
class Actor:
    actor_id: str
    label: str
    groups: set[str] = field(default_factory=set)
    kinds: set[str] = field(default_factory=set)
    msgs: list[str] = field(default_factory=list)  # time-ordered bodies


def group_actors(rows: list[dict]) -> dict[str, Actor]:
    actors: dict[str, Actor] = {}
    for r in rows:  # rows already time-ordered per actor
        a = actors.get(r["actor_id"])
        if a is None:
            a = actors[r["actor_id"]] = Actor(r["actor_id"], r["label"])
        a.groups.add(r["group_title"])
        a.kinds.add(r["group_kind"])
        a.msgs.append(r["body"])
    return actors


# ----------------------------------------------------------------------- metrics

def eer(same: np.ndarray, diff: np.ndarray) -> float:
    """Equal error rate over same-author vs different-author cosine scores."""
    if len(same) == 0 or len(diff) == 0:
        return float("nan")
    thr = np.unique(np.concatenate([same, diff]))
    best, be = 1.0, 1.0
    for t in thr:
        far = float((diff >= t).mean())   # different authors accepted
        frr = float((same < t).mean())    # same author rejected
        if abs(far - frr) < be:
            be, best = abs(far - frr), (far + frr) / 2
    return best


def eval_verification(emb: Embedder, actors: dict[str, Actor], min_msgs: int,
                      tag: str, max_authors: int = 0) -> dict:
    """Split each actor temporally into early/late halves; embed; rank."""
    labels, q_vecs, t_vecs, meta = [], [], [], []
    qualifying = [a for a in actors.values() if len(a.msgs) >= min_msgs]
    if max_authors:
        qualifying = qualifying[:max_authors]
    for a in qualifying:
        mid = len(a.msgs) // 2
        early, late = a.msgs[:mid], a.msgs[mid:]
        q_vecs.append(emb.embed(_sample(early, EPISODE_POSTS)))
        t_vecs.append(emb.embed(_sample(late, EPISODE_POSTS)))
        labels.append(a.actor_id)
        meta.append({"label": a.label, "groups": sorted(a.groups),
                     "kinds": sorted(a.kinds), "n_msgs": len(a.msgs)})
    n = len(labels)
    res = {"tag": tag, "n_authors": n, "min_msgs": min_msgs}
    if n < 2:
        res["note"] = "too few qualifying authors for a verification score"
        return res
    Q, T = np.array(q_vecs), np.array(t_vecs)

    def _metrics(Qm, Tm):
        # renormalize rows then cosine
        Qn = Qm / np.linalg.norm(Qm, axis=1, keepdims=True)
        Tn = Tm / np.linalg.norm(Tm, axis=1, keepdims=True)
        S = Qn @ Tn.T
        same = np.diag(S)
        diff = S[~np.eye(n, dtype=bool)]
        return {
            "r_at_1": round(float((S.argmax(1) == np.arange(n)).mean()), 3),
            "mean_same_cos": round(float(same.mean()), 3),
            "mean_diff_cos": round(float(diff.mean()), 3),
            "separation": round(float(same.mean() - diff.mean()), 3),
            "eer": round(eer(same, diff), 3),
        }

    # centering kills embedding anisotropy — subtract the shared mean direction.
    mu = np.vstack([Q, T]).mean(0, keepdims=True)
    res["raw"] = _metrics(Q, T)
    res["centered"] = _metrics(Q - mu, T - mu)
    res["authors"] = meta
    return res


def eval_spanish_heatmap(emb: Embedder, actors: dict[str, Actor], min_msgs: int):
    sp = {k: a for k, a in actors.items() if len(a.msgs) >= min_msgs}
    if len(sp) < 2:
        return {"note": f"only {len(sp)} spanish actors with >= {min_msgs} msgs; "
                        "heatmap skipped"}
    labels, Q, T = [], [], []
    for a in sp.values():
        mid = len(a.msgs) // 2
        Q.append(emb.embed(_sample(a.msgs[:mid], EPISODE_POSTS)))
        T.append(emb.embed(_sample(a.msgs[mid:], EPISODE_POSTS)))
        g = "+".join(sorted({x.split()[0] for x in a.groups}))
        labels.append(f"{a.label[:16]} [{g[:14]}] n={len(a.msgs)}")
    Q, T = np.array(Q), np.array(T)
    mu = np.vstack([Q, T]).mean(0, keepdims=True)  # centered = the recommended config
    Q = Q - mu; T = T - mu
    Q /= np.linalg.norm(Q, axis=1, keepdims=True)
    T /= np.linalg.norm(T, axis=1, keepdims=True)
    S = Q @ T.T

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 0.6),
                                    max(5, len(labels) * 0.55)))
    im = ax.imshow(S, cmap="viridis", vmin=-0.4, vmax=1.0)
    ax.set_xticks(range(len(labels))); ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=90, fontsize=7)
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_xlabel("target (late half)"); ax.set_ylabel("query (early half)")
    ax.set_title("LUAR cosine: Spanish actors (diagonal = same author)")
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, f"{S[i, j]:.2f}", ha="center", va="center",
                    color="white" if S[i, j] < 0.6 else "black", fontsize=6)
    fig.colorbar(im, ax=ax, shrink=0.7)
    fig.tight_layout()
    path = OUT / "spanish_heatmap.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return {"heatmap": str(path), "n_actors": len(labels),
            "diag_wins": int(sum(S[i].argmax() == i for i in range(len(labels)))),
            "labels": labels}


def eval_channel_operators(emb: Embedder, rows: list[dict], min_posts: int = 30):
    """EXPLORATORY: cluster chronological episodes within each broadcast CHANNEL."""
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import silhouette_score

    by_chan: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        if r["group_kind"] == "CHANNEL":
            by_chan[r["group_title"]].append(r["body"])  # rows are time-ordered

    results = []
    for title, posts in by_chan.items():
        if len(posts) < min_posts:
            continue
        # non-overlapping episodes of EPISODE_POSTS consecutive posts
        step = 12  # smaller episodes -> more episodes per channel to cluster over
        eps = [posts[i:i + step] for i in range(0, len(posts), step)]
        eps = [e for e in eps if len(e) >= 4]  # drop a tiny trailing episode
        if len(eps) < 4:
            continue
        V = np.array([emb.embed(e) for e in eps])
        D = 1.0 - (V @ V.T)
        np.fill_diagonal(D, 0.0)
        best_k, best_sil = 1, -1.0
        for k in range(2, min(5, len(eps))):
            lbl = AgglomerativeClustering(n_clusters=k, metric="precomputed",
                                          linkage="average").fit_predict(D)
            try:
                sil = silhouette_score(D, lbl, metric="precomputed")
            except ValueError:
                continue
            if sil > best_sil:
                best_sil, best_k = sil, k
        iu = np.triu_indices(len(eps), 1)
        results.append({
            "channel": title, "n_posts": len(posts), "n_episodes": len(eps),
            "mean_pairwise_cos": round(float((V @ V.T)[iu].mean()), 3),
            "min_pairwise_cos": round(float((V @ V.T)[iu].min()), 3),
            "best_k_by_silhouette": best_k,
            "silhouette": round(float(best_sil), 3),
            "hint": ("looks multi-style" if best_sil >= 0.15 and best_k >= 2
                     else "consistent single style"),
        })
    return {"note": "EXPLORATORY — no post_author ground truth on this data",
            "channels": results}


# ---------------------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups", choices=["spanish", "baseline", "both"],
                    default="spanish")
    ap.add_argument("--spanish-min", type=int, default=8,
                    help="min usable msgs per actor for the spanish evals")
    ap.add_argument("--baseline-min", type=int, default=40,
                    help="min usable msgs per actor for the corpus-wide baseline")
    ap.add_argument("--max-authors", type=int, default=300,
                    help="cap baseline authors (0 = all) to keep the run quick")
    ap.add_argument("--model", default=MODEL_NAME)
    args = ap.parse_args()

    report: dict = {"model": args.model, "max_tokens": MAX_TOKENS,
                    "episode_posts": EPISODE_POSTS}

    print(f"[luar-poc] loading {args.model} ...", file=sys.stderr)
    emb = Embedder(args.model)
    print(f"[luar-poc] device = {emb.dev}", file=sys.stderr)

    if args.groups in ("spanish", "both"):
        print("[luar-poc] fetching spanish target groups ...", file=sys.stderr)
        rows = fetch_spanish()
        actors = group_actors(rows)
        report["spanish_rows"] = len(rows)
        report["spanish_actors_total"] = len(actors)
        report["spanish_verification"] = eval_verification(
            emb, actors, args.spanish_min, "spanish")
        report["spanish_heatmap"] = eval_spanish_heatmap(
            emb, actors, args.spanish_min)
        report["channel_operators"] = eval_channel_operators(emb, rows)

    if args.groups in ("baseline", "both"):
        print("[luar-poc] fetching corpus-wide CHAT baseline ...", file=sys.stderr)
        brows = fetch_baseline(args.baseline_min)
        bactors = group_actors(brows)
        report["baseline_rows"] = len(brows)
        report["baseline_actors_total"] = len(bactors)
        report["baseline_verification"] = eval_verification(
            emb, bactors, args.baseline_min, "baseline", max_authors=args.max_authors)

    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n[luar-poc] wrote {OUT/'report.json'}", file=sys.stderr)


# ponytail: the runnable check — EER monotonicity + perfect-separation sanity.
def _selfcheck():
    import numpy as _np
    assert abs(eer(_np.array([0.9, 0.8]), _np.array([0.1, 0.2]))) < 1e-9, "sep->0 EER"
    e = eer(_np.array([0.5, 0.6]), _np.array([0.4, 0.55]))
    assert 0.0 <= e <= 1.0, "EER in range"
    assert _sample([1, 2, 3, 4, 5], 3) == [1, 3, 5], "even subsample"
    print("selfcheck ok")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        _selfcheck()
    else:
        main()
