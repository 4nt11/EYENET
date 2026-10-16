#!/usr/bin/env python3
"""PoC: gazetteer (dictionary) match for malware + threat groups over the corpus.

Counterpart to extract.py (GLiNER). These entities are a closed set, so we match
MITRE ATT&CK names/aliases with word boundaries instead of asking a model to guess.
Compare precision+recall against GLiNER's failed malware/threat-group labels.

    python development/poc-gliner/build_gazetteer.py        # once, builds gazetteer.json
    python development/poc-gliner/match_gazetteer.py --source-kind forum
    python development/poc-gliner/match_gazetteer.py --selfcheck
"""
from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent


def compile_gaz(gaz: dict[str, list[str]]) -> dict[str, re.Pattern]:
    pats = {}
    for cat, terms in gaz.items():
        # longest-first so "Cobalt Strike" wins over a bare word; \b avoids substrings.
        alt = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
        pats[cat] = re.compile(rf"\b(?:{alt})\b", re.IGNORECASE)
    return pats


def match_text(text: str, pats: dict[str, re.Pattern]) -> list[dict]:
    out = []
    for cat, pat in pats.items():
        for m in pat.finditer(text):
            out.append({"label": cat, "text": m.group(0)})
    return out


def who_what_when(rows: list[dict]) -> dict:
    agg: dict = defaultdict(lambda: defaultdict(Counter))
    for r in rows:
        akey = r.get("actor_key") or "?"
        for e in r["entities"]:
            agg[akey][e["label"]][e["text"].lower()] += 1
    return agg


def selfcheck() -> None:
    pats = compile_gaz({"malware": ["Emotet", "Cobalt Strike"], "threat_group": ["APT28"]})
    assert match_text("deployed Emotet via a loader", pats)[0]["text"] == "Emotet"
    assert [e["text"] for e in match_text("used Cobalt Strike beacon", pats)] == ["Cobalt Strike"]
    assert match_text("APT28 hit them", pats)[0]["label"] == "threat_group"
    # word boundary: must NOT match inside another word
    assert match_text("emotetheory is not malware", pats) == []
    print("selfcheck OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, default=HERE / "sample.jsonl")
    ap.add_argument("--gazetteer", type=Path, default=HERE / "gazetteer.json")
    ap.add_argument("--source-kind", default=None)
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--review-n", type=int, default=120)
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        selfcheck()
        return

    pats = compile_gaz(json.loads(args.gazetteer.read_text()))
    rows = [json.loads(l) for l in args.corpus.open(encoding="utf-8") if l.strip()]
    if args.source_kind:
        rows = [r for r in rows if (r.get("source_kind") or "").lower() == args.source_kind.lower()]
    rows = rows[:args.limit]
    print(f"loaded {len(rows)} messages")

    for r in rows:
        r["entities"] = match_text(r["text"], pats)

    label_counts = Counter(e["label"] for r in rows for e in r["entities"])
    surface = Counter((e["label"], e["text"].lower()) for r in rows for e in r["entities"])
    n_with = sum(1 for r in rows if r["entities"])
    print(f"\n=== gazetteer stats ===")
    print(f"messages with >=1 hit : {n_with}/{len(rows)} ({100*n_with/max(len(rows),1):.1f}%)")
    for lbl, c in label_counts.most_common():
        print(f"  {lbl:15s} {c}")
    print("\ntop surfaces:")
    for (lbl, s), c in surface.most_common(25):
        print(f"  {c:4d} {lbl:13s} {s}")

    # review dump (manual precision)
    flat = [(r, e) for r in rows for e in r["entities"]]
    random.seed(0)
    with (HERE / "review_gaz.txt").open("w", encoding="utf-8") as f:
        f.write("# y=real mention  n=false positive. Tally per label.\n\n")
        for r, e in random.sample(flat, min(args.review_n, len(flat))):
            ctx = r["text"].replace("\n", " ")
            i = ctx.lower().find(e["text"].lower())
            snip = ctx[max(0, i - 45):i + len(e["text"]) + 45]
            f.write(f"[ ] {e['label']:13s} | {e['text']!r:24s} | …{snip}…\n")
    print(f"\nwrote review_gaz.txt ({min(args.review_n, len(flat))} items)")


if __name__ == "__main__":
    main()
