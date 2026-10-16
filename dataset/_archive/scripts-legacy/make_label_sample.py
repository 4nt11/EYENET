#!/usr/bin/env python3
"""Build a ~260-msg stratified labeling sample from silver_multilabel.jsonl.

Goals: (1) spread roughly evenly across all groups so no channel dominates;
(2) within each group mix silver-POSITIVE rows (fast confirm) with silver-NONE
rows -- the none rows are where semantic labels hide (esp. actor_ops in NEXUSEC,
which the prefilter can't tag). Keeps silver columns so labeler.html pre-fills toggles.

Output: dataset/label_sample.jsonl  ->  load in labeler.html.
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
LABELS = ["incident", "leak", "infostealer", "access_sale", "actor_ops", "tooling"]
SEED = 20260926
CAP = 24                       # per-group target
BOOST = {"NEXUSEC": 40}        # actor_ops lives here and is silver-invisible
POS_FRAC = 0.5                 # aim half silver-positive, half none (per group)
SUPP = 22                      # extra candidate rows per silver-blind head (tooling/actor_ops)

# The two silver-blind heads have no prefilter signal, so the even-group sample
# barely covers them. These surface CANDIDATES (unseeded — you confirm/reject).
# tooling = tool/service SALE (exclude /attack commands + check-host attack brags).
_TOOL_NOUN = r"(?:web ?shell|shell|ddos|booter|stress(?:er|ing)?|dstat|\bL7\b|cnc|rat\b|malware|loader|stealer|builder|checker|combo|cracked?|worm(?:gpt)?|exploit|panel|method|tool)"
_SALE_CUE = r"(?:for sale|selling|sell\b|wts\b|rent|service drop|price|\$\d|promo|offering|build your own)"
RE_TOOL = re.compile(rf"(?i)(?=.*{_TOOL_NOUN})(?=.*{_SALE_CUE})")
RE_ATTACK_CMD = re.compile(r"(?i)(?:^|\s)/(?:attack|ddos|flood|scan)\b|check-host\.net")
RE_ACTOR = re.compile(r"(?i)\b(announc\w*|recruit\w*|join us|alliance|we will|we are|upcoming|coming soon|manifesto|call to action|official (?:channel|alliance|announcement)|new leader|deploy\w*)\b")


def main() -> None:
    rng = random.Random(SEED)
    rows = [json.loads(x) for x in (HERE / "silver_multilabel.jsonl").read_text("utf-8").splitlines() if x.strip()]
    by_group: dict[str, list[dict]] = defaultdict(list)
    seen: set[str] = set()
    for r in rows:
        t = r["text"]
        if t in seen:
            continue
        seen.add(t)
        by_group[r.get("group") or "?"].append(r)

    picked: list[dict] = []
    for g, items in by_group.items():
        quota = min(BOOST.get(g, CAP), len(items))
        pos = [r for r in items if any(r.get(k) for k in LABELS)]
        neg = [r for r in items if not any(r.get(k) for k in LABELS)]
        rng.shuffle(pos)
        rng.shuffle(neg)
        n_pos = min(len(pos), round(quota * POS_FRAC))
        n_neg = min(len(neg), quota - n_pos)
        n_pos = min(len(pos), quota - n_neg)   # backfill if one side is short
        picked += pos[:n_pos] + neg[:n_neg]

    # Supplement: surface candidates for the two silver-blind heads so they're labelable.
    chosen = {r["text"] for r in picked}
    all_rows = [r for items in by_group.values() for r in items]

    def supplement(pred, n):
        cands = [r for r in all_rows if r["text"] not in chosen and pred(r["text"])]
        rng.shuffle(cands)
        for r in cands[:n]:
            picked.append(r)
            chosen.add(r["text"])

    supplement(lambda t: bool(RE_TOOL.search(t)) and not RE_ATTACK_CMD.search(t), SUPP)
    supplement(lambda t: bool(RE_ACTOR.search(t)) and not RE_ATTACK_CMD.search(t), SUPP)

    rng.shuffle(picked)   # unbiased labeling order (labeler can still filter by channel)
    out = HERE / "label_sample.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in picked:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    grp = Counter(r.get("group") for r in picked)
    lab = Counter()
    none = 0
    for r in picked:
        fired = [k for k in LABELS if r.get(k)]
        none += not fired
        for k in fired:
            lab[k] += 1
    print(f"{len(picked)} rows -> {out.name}")
    print("per group :", dict(grp.most_common()))
    print("silver pos:", {k: lab[k] for k in LABELS}, f"| silver-none: {none}")
    print("(silver-none rows are yours to read: actor_ops + any silver misses live there)")


if __name__ == "__main__":
    main()
