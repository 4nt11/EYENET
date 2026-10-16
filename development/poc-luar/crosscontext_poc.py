#!/usr/bin/env python
"""Cross-context authorship linkage bake-off: the test EYENET actually faces.

Ground truth = same Telegram ``platform_userid`` posting in TWO different groups.
For each such person we take their two biggest group-piles (two CONTEXTS) and ask
every method: are these two piles the same hand?

We score the identical person set two ways, so the degradation is clean:

  * same_context  -- split pile A in half (A1 query vs A2 target). Same person,
    same group => topic held roughly constant. The EASY question.
  * cross_context -- pile A (group X) vs pile B (group Y). Same person, different
    group => different topic/audience. The OPERATIONAL question.

Methods, apples-to-apples (query x target similarity -> R@1, EER, AUC):

  EYENET shipped (reproduced faithfully, standalone):
    * eyenet_char3_simhash   char-trigram freq -> 64-bit simhash, Hamming
    * eyenet_fnword_simhash  top-50 function-word rel-freq -> simhash, Hamming
      (these are the comparators DISABLED for Spanish; Rutify M5 AUC 0.55 / 0.68)

  Full distributions (no lossy 64-bit quantization):
    * full_char3_js          Jensen-Shannon over char-trigram distributions
    * full_char4_jaccard     Jaccard over char-4gram sets
    * burrows_delta          z-scored top-word freq, Manhattan

  Neural:
    * luar_centered          LUAR-MUD episode embedding, mean-centered cosine

The simhash + function-word recipes are copied verbatim (with citation) from
eyenet/sensor/primitives/{character_ngram_simhash,function_word_distribution_top50}.py
and eyenet/sensor/primitives/_simhash.py so the PoC stays standalone.

Run:  ./.venv/bin/python crosscontext_poc.py --min-msgs 8
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter

import numpy as np

from classic_poc import (burrows_dist, burrows_z, cosine_dist, jaccard_dist,
                         js_dist, ngram_prob, ngram_sets, tfidf_rareword)
from luar_poc import EPISODE_POSTS, OUT, eer, pg_csv

# --------------------------------------------------- EYENET simhash (reproduced)
# verbatim from eyenet/sensor/primitives/_simhash.py
_FNV_PRIME = 0x100000001B3
_FNV_OFFSET = 0xCBF29CE484222325


def _fnv1a_64(data: bytes) -> int:
    h = _FNV_OFFSET
    for byte in data:
        h ^= byte
        h = (h * _FNV_PRIME) & 0xFFFFFFFFFFFFFFFF
    return h


def simhash64(features: dict[str, float]) -> int:
    v = [0.0] * 64
    for feature, weight in features.items():
        h = _fnv1a_64(feature.encode("utf-8"))
        for i in range(64):
            v[i] += weight if (h & (1 << i)) else -weight
    bits = 0
    for i in range(64):
        if v[i] > 0:
            bits |= 1 << i
    return bits


def hamming64(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# char_ngram primitive: char trigrams, lowercased (NGRAM_SIZE=3)
def eyenet_char3_fp(concat_text: str) -> int:
    lo = concat_text.lower()
    freq = Counter(lo[i:i + 3] for i in range(len(lo) - 2))
    return simhash64({k: float(v) for k, v in freq.items()})


# function_word primitive: top-50 function words, ES/EN by vote, relative freq
_FW_EN = ("the of and to a in is it you that he was for on are with as at be this "
          "have from or one had by not but what all were we when your can said there "
          "use an each which she do how their if will up other about").split()
_FW_ES = ("de la que el en y a los del se las un por con una su para es al lo como más "
          "pero sus le ya o fue este ha sí porque esta entre cuando muy sin sobre ser "
          "tiene también me hasta hay donde han quien están estado desde").split()
_TOKENIZE = re.compile(r"[a-záéíóúüñàèìòùâêîôûäëïöü']+", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKENIZE.finditer(text)]


def eyenet_fnword_fp(bodies: list[str]) -> int:
    token_lists = [_tokens(b) for b in bodies]
    en, es = set(_FW_EN), set(_FW_ES)
    es_score = sum(len(set(t) & es) for t in token_lists)
    en_score = sum(len(set(t) & en) for t in token_lists)
    words = _FW_ES if es_score > en_score else _FW_EN
    fw = set(words)
    freq = dict.fromkeys(words, 0)
    total = 0
    for t in token_lists:
        for w in t:
            if w in fw:
                freq[w] += 1
                total += 1
    if total == 0:
        return 0
    return simhash64({w: freq[w] / total for w in words})


# ------------------------------------------------------------------------ metrics

def auc(same: np.ndarray, diff: np.ndarray) -> float:
    s, d = np.asarray(same)[:, None], np.asarray(diff)[None, :]
    return float(((s > d).sum() + 0.5 * (s == d).sum()) / (s.size * d.size))


def _metrics_from_sim(S: np.ndarray) -> dict:
    n = S.shape[0]
    same = np.diag(S)
    diff = S[~np.eye(n, dtype=bool)]
    return {
        "r_at_1": round(float((S.argmax(1) == np.arange(n)).mean()), 3),
        "eer": round(eer(same, diff), 3),
        "auc": round(auc(same, diff), 3),
        "mean_same": round(float(same.mean()), 3),
        "mean_diff": round(float(diff.mean()), 3),
    }


# ------------------------------------------------------------------- method sims
# each returns an n x n query(row) x target(col) SIMILARITY matrix (higher=same)

def sim_eyenet_char3(q_piles, t_piles):
    qf = [eyenet_char3_fp(" ".join(p)) for p in q_piles]
    tf = [eyenet_char3_fp(" ".join(p)) for p in t_piles]
    return np.array([[64 - hamming64(a, b) for b in tf] for a in qf], dtype=float)


def sim_eyenet_fnword(q_piles, t_piles):
    qf = [eyenet_fnword_fp(p) for p in q_piles]
    tf = [eyenet_fnword_fp(p) for p in t_piles]
    return np.array([[64 - hamming64(a, b) for b in tf] for a in qf], dtype=float)


def _full_dist_sim(q_piles, t_piles, builder, dister):
    docs = [" ".join(p) for p in q_piles] + [" ".join(p) for p in t_piles]
    n = len(q_piles)
    rep = builder(docs)
    D = dister(rep, np.arange(n), np.arange(n, 2 * n))
    return -D  # distance -> similarity


def sim_full_char3_js(q, t):
    return _full_dist_sim(q, t, lambda d: ngram_prob(d, n=3), js_dist)


def sim_full_char4_jacc(q, t):
    return _full_dist_sim(q, t, lambda d: ngram_sets(d, n=4), jaccard_dist)


def sim_burrows(q, t):
    return _full_dist_sim(q, t, burrows_z, burrows_dist)


def sim_distinctive_vocab(q, t):
    return _full_dist_sim(q, t, tfidf_rareword, cosine_dist)


def sim_luar(q_piles, t_piles, emb):
    def _ep(p):
        import numpy as _np
        k = EPISODE_POSTS
        if len(p) <= k:
            return p
        idx = _np.linspace(0, len(p) - 1, k).round().astype(int)
        return [p[i] for i in idx]
    Q = np.array([emb.embed(_ep(p)) for p in q_piles])
    T = np.array([emb.embed(_ep(p)) for p in t_piles])
    mu = np.vstack([Q, T]).mean(0, keepdims=True)
    Q, T = Q - mu, T - mu
    Q /= np.linalg.norm(Q, axis=1, keepdims=True)
    T /= np.linalg.norm(T, axis=1, keepdims=True)
    return Q @ T.T


# ---------------------------------------------------------------------------- data

def fetch_cross_context(min_msgs: int) -> list[dict]:
    sql = f"""
      WITH base AS (
        SELECT a.platform_userid AS pid,
               coalesce(nullif(a.current_handle,''), left(a.platform_userid,12)) AS label,
               m.group_id, g.current_title AS gtitle, g.kind::text AS kind,
               m.sent_at_source AS ts, m.body
        FROM message m JOIN actor a ON m.actor_id=a.id JOIN group_ g ON m.group_id=g.id
        LEFT JOIN content_template c ON m.template_id=c.id
        WHERE m.length_words>=5 AND coalesce(c.is_copypasta,false)=false
          AND a.platform_userid IS NOT NULL AND a.platform_userid<>''
          AND m.body IS NOT NULL AND length(trim(m.body))>0
      ),
      pg AS (SELECT pid, group_id, count(*) n FROM base GROUP BY pid, group_id),
      qual_pg AS (SELECT pid, group_id FROM pg WHERE n >= {min_msgs}),
      qual_pid AS (SELECT pid FROM qual_pg GROUP BY pid HAVING count(*) >= 2)
      SELECT b.pid, b.label, b.group_id, b.gtitle, b.kind, b.ts, b.body
      FROM base b
      JOIN qual_pg q ON b.pid=q.pid AND b.group_id=q.group_id
      JOIN qual_pid p ON b.pid=p.pid
      ORDER BY b.pid, b.group_id, b.ts
    """
    return pg_csv(sql)


def fetch_cross_source(min_msgs: int) -> list[dict]:
    """Author-centric CROSS-PLATFORM silver GT: same NORMALIZED handle on >=2
    different sources (darkforums / raidforums / pwnforums / telegram ...).
    Keyed on the normalized handle so build_persons treats each source as a
    'group' (= a context). Caveat: same-handle-across-forums is strong but not
    perfect evidence (handle squatting exists in these scenes)."""
    sql = f"""
      WITH base AS (
        SELECT regexp_replace(lower(a.current_handle),'[^a-z0-9]','','g') AS pid,
               a.current_handle AS label,
               a.source_id AS group_id, s.display_name AS gtitle, s.kind::text AS kind,
               m.sent_at_source AS ts, m.body
        FROM message m JOIN actor a ON m.actor_id=a.id JOIN source s ON a.source_id=s.id
        LEFT JOIN content_template c ON m.template_id=c.id
        WHERE m.length_words>=5 AND coalesce(c.is_copypasta,false)=false
          AND m.body IS NOT NULL AND length(trim(m.body))>0
          AND a.current_handle IS NOT NULL
          AND length(regexp_replace(lower(a.current_handle),'[^a-z0-9]','','g'))>=4
      ),
      pg AS (SELECT pid, group_id, count(*) n FROM base GROUP BY pid, group_id),
      qual_pg AS (SELECT pid, group_id FROM pg WHERE n >= {min_msgs}),
      qual_pid AS (SELECT pid FROM qual_pg GROUP BY pid HAVING count(*) >= 2)
      SELECT b.pid, b.label, b.group_id, b.gtitle, b.kind, b.ts, b.body
      FROM base b
      JOIN qual_pg q ON b.pid=q.pid AND b.group_id=q.group_id
      JOIN qual_pid p ON b.pid=p.pid
      ORDER BY b.pid, b.group_id, b.ts
    """
    return pg_csv(sql)


def build_persons(rows: list[dict]):
    """-> list of dicts: {label, pileA(list), pileB(list), gA, gB, spanish(bool)}"""
    by_pid: dict[str, dict] = {}
    for r in rows:
        p = by_pid.setdefault(r["pid"], {"label": r["label"], "groups": {}})
        g = p["groups"].setdefault(r["group_id"], {"title": r["gtitle"], "msgs": []})
        g["msgs"].append(r["body"])
    persons = []
    for p in by_pid.values():
        top = sorted(p["groups"].values(), key=lambda g: len(g["msgs"]), reverse=True)[:2]
        if len(top) < 2:
            continue
        titles = (top[0]["title"] + " " + top[1]["title"]).lower()
        persons.append({
            "label": p["label"],
            "pileA": top[0]["msgs"], "pileB": top[1]["msgs"],
            "gA": top[0]["title"], "gB": top[1]["title"],
            "spanish": any(k in titles for k in ("soulhem", "mortem", "pampa")),
        })
    return persons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-msgs", type=int, default=8,
                    help="min usable msgs per context")
    ap.add_argument("--mode", choices=["cross-group", "cross-source"],
                    default="cross-source",
                    help="cross-group = same user, 2 groups; cross-source = same "
                         "handle, 2 platforms (author-centric silver GT)")
    ap.add_argument("--no-luar", action="store_true")
    args = ap.parse_args()

    rows = (fetch_cross_source(args.min_msgs) if args.mode == "cross-source"
            else fetch_cross_context(args.min_msgs))
    persons = build_persons(rows)
    n = len(persons)
    ctx = "cross-source (platforms)" if args.mode == "cross-source" else "cross-group"
    print(f"[xctx] mode={args.mode}: {n} {ctx} persons (min {args.min_msgs} msgs/context), "
          f"{sum(p['spanish'] for p in persons)} touch a spanish target group")
    if n < 3:
        print("too few persons; lower --min-msgs")
        return

    # same-context piles: split pile A temporally
    sc_q = [p["pileA"][:len(p["pileA"]) // 2] for p in persons]
    sc_t = [p["pileA"][len(p["pileA"]) // 2:] for p in persons]
    # cross-context piles: A vs B
    cc_q = [p["pileA"] for p in persons]
    cc_t = [p["pileB"] for p in persons]

    methods = [
        ("eyenet_char3_simhash", sim_eyenet_char3),
        ("eyenet_fnword_simhash", sim_eyenet_fnword),
        ("full_char3_js", sim_full_char3_js),
        ("full_char4_jaccard", sim_full_char4_jacc),
        ("burrows_delta", sim_burrows),
        ("distinctive_vocab", sim_distinctive_vocab),
    ]
    emb = None
    if not args.no_luar:
        from luar_poc import Embedder
        print("[xctx] loading LUAR ...")
        emb = Embedder()

    report = {"n_persons": n, "min_msgs": args.min_msgs,
              "n_spanish": sum(p["spanish"] for p in persons),
              "same_context": {}, "cross_context": {}}
    for name, fn in methods:
        report["same_context"][name] = _metrics_from_sim(fn(sc_q, sc_t))
        report["cross_context"][name] = _metrics_from_sim(fn(cc_q, cc_t))
    if emb is not None:
        report["same_context"]["luar_centered"] = _metrics_from_sim(sim_luar(sc_q, sc_t, emb))
        report["cross_context"]["luar_centered"] = _metrics_from_sim(sim_luar(cc_q, cc_t, emb))

    (OUT / "crosscontext.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))

    order = [m[0] for m in methods] + (["luar_centered"] if emb is not None else [])
    print(f"\n{'method':22s} | {'SAME-ctx AUC/EER/R@1':>22s} | {'CROSS-ctx AUC/EER/R@1':>22s} | dAUC")
    print("-" * 86)
    for name in order:
        s, c = report["same_context"][name], report["cross_context"][name]
        d = round(c["auc"] - s["auc"], 3)
        print(f"{name:22s} | {s['auc']:>5}/{s['eer']:>5}/{s['r_at_1']:>5}      "
              f"| {c['auc']:>5}/{c['eer']:>5}/{c['r_at_1']:>5}      | {d:+.3f}")
    print(f"\n[xctx] wrote {OUT/'crosscontext.json'}")


if __name__ == "__main__":
    main()
