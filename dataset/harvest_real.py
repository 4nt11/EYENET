#!/usr/bin/env python3
"""Continue the fine-tune with REAL data mined from decision_log.jsonl.

Silver-labels from the model's own calls on the 8264-msg corpus:
  POS = prefilter adjudicated AND mmbert_p>=0.7  (strong structural + semantic agree)
  NEG = short (<40 chars), no structural signal, no dump keyword  (benign chatter —
        the "hi"/"sup"/"@handle hai" class that mmBERT currently false-positives on)

Redacts (substitution, via build_dataset) and holds out 20% per class as a real
test slice that is NEVER trained on. Writes real_train.jsonl / real_test.jsonl.
Ambiguous middle (negotiation/commerce) is left OUT — no noisy labels.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import build_dataset as bd

HERE = Path(__file__).parent
DUMPKW = re.compile(r"(?i)breach|leak|database|dump|combo|\.onion|dork|stealer|\bpass\b|"
                    r"carding|\brat\b|botnet|ddos|deface|hacked|sql|shell|0day|cve|\.gov|\.mil")
NEG_CAP = 1800  # cap negatives so the set isn't 6:1; still negative-leaning (real base rate)


def main() -> None:
    random.seed(0)
    rows = [json.loads(x) for x in (HERE / "decision_log.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]

    pos = [r for r in rows if r["pf_adjudicate"] and r["mmbert_p"] >= 0.7]
    neg = [r for r in rows if len(r["text"]) < 40 and not r["prefilter"] and not DUMPKW.search(r["text"])]
    random.shuffle(neg)
    neg = neg[:NEG_CAP]

    def mk(rs, label):
        return [{"text": bd.redact(r["text"]), "label": label, "source": "real"} for r in rs]

    pos_r, neg_r = mk(pos, 1), mk(neg, 0)
    random.shuffle(pos_r)
    random.shuffle(neg_r)

    def split(rs):  # 80/20
        k = max(1, round(len(rs) * 0.2))
        return rs[k:], rs[:k]

    ptr, pte = split(pos_r)
    ntr, nte = split(neg_r)
    train = ptr + ntr
    test = pte + nte
    random.shuffle(train)
    random.shuffle(test)

    for name, rs in (("real_train", train), ("real_test", test)):
        with open(HERE / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for r in rs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        p = sum(x["label"] for x in rs)
        print(f"{name}: {len(rs)} ({p} pos / {len(rs)-p} neg)")


if __name__ == "__main__":
    main()
