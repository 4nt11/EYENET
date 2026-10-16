#!/usr/bin/env python3
"""PoC: GLiNER zero-shot entity extraction over the real EYENET corpus.

Measures whether GLiNER pulls useful FUZZY entities (org/threat-group/alias/
malware/tool/location) at eyeball-usable precision, ES+EN. Deterministic entities
(wallets/CVE/onion/IP/hash) are regex's job and are NOT tested here.

Run:
    pip install gliner                       # PoC-only dep, isolated to this dir
    python development/poc-gliner/extract.py            # uses sample.jsonl
    python development/poc-gliner/extract.py --selfcheck # no model, tests aggregation

Outputs (next to this file):
    entities.jsonl  one row per message with its entities
    review.txt      random sample of extractions w/ context -> manual precision tally
    (stdout)        stats + a who/what/when demo proving the deliverable
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
# Fuzzy labels only — the stuff regex genuinely can't do. Edit freely; this is the
# knob the whole PoC turns on. v2: dropped the greedy generics (location/org/alias)
# that drowned the signal in combolist columns and pronouns. Sharp CTI set only.
LABELS = [
    "malware",
    "threat actor or hacking group",
    "breached company or organization",
]


def load_corpus(path: Path, limit: int | None, source_kind: str | None) -> list[dict]:
    rows = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    if source_kind:
        rows = [r for r in rows if (r.get("source_kind") or "").lower() == source_kind.lower()]
    if limit:
        rows = rows[:limit]
    return rows


def who_what_when(ents_by_msg: list[dict]) -> dict:
    """The actual deliverable: per-actor entity mentions over time.

    Returns {actor_key: {label: Counter(entity_text)}} plus first/last seen.
    """
    agg: dict = defaultdict(lambda: defaultdict(Counter))
    seen: dict = defaultdict(lambda: [None, None])  # actor -> [first, last] sent_at
    for row in ents_by_msg:
        akey = row.get("actor_key") or "?"
        sent = row.get("sent_at")
        if sent:
            lo, hi = seen[akey]
            seen[akey] = [min(lo, sent) if lo else sent, max(hi, sent) if hi else sent]
        for e in row["entities"]:
            agg[akey][e["label"]][e["text"].strip().lower()] += 1
    return {"mentions": agg, "seen": seen}


def selfcheck() -> None:
    fake = [
        {"actor_key": "actor:a", "sent_at": "2026-03-01", "entities": [
            {"label": "malware", "text": "RedLine"}, {"label": "malware", "text": "redline"}]},
        {"actor_key": "actor:a", "sent_at": "2026-01-01", "entities": [
            {"label": "hacking tool or software", "text": "Cobalt Strike"}]},
        {"actor_key": "actor:b", "sent_at": "2026-05-01", "entities": []},
    ]
    r = who_what_when(fake)
    assert r["mentions"]["actor:a"]["malware"]["redline"] == 2, "case-fold merge broke"
    assert r["seen"]["actor:a"] == ["2026-01-01", "2026-03-01"], "first/last seen broke"
    assert "actor:b" in r["seen"], "empty-entity actor dropped"
    print("selfcheck OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, default=HERE / "sample.jsonl")
    ap.add_argument("--model", default="urchade/gliner_multi-v2.1")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--source-kind", default=None, help="filter e.g. forum")
    ap.add_argument("--review-n", type=int, default=120)
    ap.add_argument("--device", default="auto", help="cuda | cpu | auto")
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        selfcheck()
        return

    corpus_path = args.corpus
    if not corpus_path.exists():
        # fall back to the stale corpus so the pipeline is runnable before sample.sh
        corpus_path = Path(__file__).parents[1] / "dataset" / "eyenet_messages.jsonl"
        print(f"[warn] {args.corpus} missing; smoke-testing on stale {corpus_path.name}")

    rows = load_corpus(corpus_path, args.limit, args.source_kind)
    print(f"loaded {len(rows)} messages from {corpus_path.name}")

    import torch
    from gliner import GLiNER  # lazy: heavy import only on the real path

    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model = GLiNER.from_pretrained(args.model).to(device)
    print(f"model on {device}" + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else ""))

    # ponytail: the model's processor hard-caps at 384 tokens anyway, so the [:2000]
    # char cut just keeps batching cheap. Real pipeline needs sliding-window chunking
    # for long threads — out of scope for measuring extraction quality.
    texts = [r["text"][:2000] for r in rows]
    preds = []
    for i in range(0, len(texts), args.batch_size):
        preds.extend(model.batch_predict_entities(
            texts[i:i + args.batch_size], LABELS, threshold=args.threshold))
        print(f"  {min(i + args.batch_size, len(texts))}/{len(texts)}", end="\r")
    print()

    out = []
    for r, ents in zip(rows, preds):
        out.append({
            "msg_id": r.get("msg_id"), "actor_key": r.get("actor_key"),
            "source_kind": r.get("source_kind"), "sent_at": r.get("sent_at"),
            "text": r["text"], "entities": ents,
        })
    (HERE / "entities.jsonl").write_text(
        "\n".join(json.dumps(o, ensure_ascii=False) for o in out) + "\n", encoding="utf-8")

    # ---- stats ----
    label_counts = Counter(e["label"] for o in out for e in o["entities"])
    n_with = sum(1 for o in out if o["entities"])
    total_ents = sum(len(o["entities"]) for o in out)
    print(f"\n=== extraction stats (threshold={args.threshold}) ===")
    print(f"messages with >=1 entity : {n_with}/{len(out)} ({100*n_with/max(len(out),1):.1f}%)")
    print(f"total entities           : {total_ents}  ({total_ents/max(len(out),1):.2f}/msg)")
    for lbl, c in label_counts.most_common():
        print(f"  {lbl:32s} {c}")

    # ---- manual-precision review dump ----
    flat = [(o, e) for o in out for e in o["entities"]]
    random.seed(0)
    sample = random.sample(flat, min(args.review_n, len(flat)))
    with (HERE / "review.txt").open("w", encoding="utf-8") as f:
        f.write("# Mark each: y=correct  n=wrong  ?=debatable. Tally y/(y+n) per label.\n\n")
        for o, e in sample:
            ctx = o["text"].replace("\n", " ")
            i = ctx.lower().find(e["text"].lower())
            snippet = ctx[max(0, i - 40):i + len(e["text"]) + 40] if i >= 0 else ctx[:80]
            f.write(f"[ ] {e['label']:28s} | {e['text']!r:30s} | {e['score']:.2f} | …{snippet}…\n")
    print(f"\nwrote review.txt ({len(sample)} items) -> eyeball precision per label")

    # ---- who/what/when demo (the actual deliverable) ----
    www = who_what_when(out)
    ranked = sorted(www["mentions"].items(),
                    key=lambda kv: sum(sum(c.values()) for c in kv[1].values()), reverse=True)
    print("\n=== who/what/when demo (top 5 actors by mention volume) ===")
    for akey, labels in ranked[:5]:
        lo, hi = www["seen"][akey]
        print(f"\n{akey}  seen {lo} .. {hi}")
        for lbl, counter in labels.items():
            top = ", ".join(f"{t}×{n}" for t, n in counter.most_common(5))
            if top:
                print(f"  {lbl:28s}: {top}")


if __name__ == "__main__":
    main()
