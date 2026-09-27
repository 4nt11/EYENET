#!/usr/bin/env python3
"""Build laya train/test sets from real data.md + synthetic.jsonl.

Rules ([[project_laya_finetune_experiment]]):
- REDACT specifics -> typed placeholders so laya learns register, not victims, and
  no real stolen data lands in weights. Case-INSENSITIVE (models uppercase values).
  Synthetic: exact-replace the recorded `entities` first, then the structural pass.
  Keep scene vocabulary (DATABASE, HACKED BY, check-host.net) — that IS the signal.
- SPLIT real 70/30. The 30% test slice is NEVER in training. Synthetic is train-only.
- Eval negatives come from the hand-authored benign set in laya_eval.py (kept real,
  not generated), so specificity is measured against non-synthetic text.

Out: dataset/train.jsonl, dataset/test.jsonl  ({text,label,source}).
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

HERE = Path(__file__).parent
REAL = HERE / "data.md"
SYN = HERE / "synthetic.jsonl"

# Redact by SUBSTITUTION with plausible fakes, NOT distinctive <TAGS>. Tagging
# leaked the label: positives were placeholder-dense, benign chatter wasn't, so the
# classifier shortcut on "<URL> present -> incident" (confirmed FPs on benign+URL).
# Fakes scrub the real victim/handle/etc without leaving a token tell. Deterministic
# (same value -> same fake) so a message stays internally consistent.
_FAKE_DOMAINS = ["examplecorp.com", "portal-demo.net", "acme-site.org", "servicio-x.co",
                 "data-hub.io", "civic-portal.gov", "med-center.co.id", "univ-demo.ac.id"]
_FAKE_HANDLES = ["@user_7f", "@contact_ab", "@channel_x9", "@vendor_qz", "@admin_k3"]


def _pick(pool: list[str], key: str) -> str:
    h = int(hashlib.md5(key.lower().encode()).hexdigest(), 16)  # noqa: S324 (non-crypto)
    return pool[h % len(pool)]


def _fake_ip(m: re.Match[str]) -> str:
    h = int(hashlib.md5(m.group(0).encode()).hexdigest(), 16)  # noqa: S324
    return f"10.{h % 250}.{(h // 250) % 250}.{(h // 62500) % 250}"


_SUBS: list[tuple[re.Pattern[str], object]] = [
    (re.compile(r"(?i)[\w.+-]{1,64}@[\w-]{1,63}\.[a-z]{2,24}:\S{3,40}"), lambda m: "user@mail.tld:pass"),
    (re.compile(r"(?i)\b05[a-f0-9]{64}\b"), lambda m: "05" + "ab" * 32),
    (re.compile(r"(?i)\b0x[a-f0-9]{40}\b"), lambda m: "0x" + "de" * 20),
    (re.compile(r"\b(?:bc1[a-z0-9]{25,59}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b"), lambda m: "bc1qexamplewalletxxxxxxxxxxxxxxxxxxxx"),
    (re.compile(r"(?i)https?://\S+"), lambda m: "https://" + _pick(_FAKE_DOMAINS, m.group(0))),
    (re.compile(r"(?i)(?:t\.me/|@)[a-z0-9_]{4,32}"), lambda m: _pick(_FAKE_HANDLES, m.group(0))),
    (re.compile(r"(?i)\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,24}\b"), lambda m: _pick(_FAKE_DOMAINS, m.group(0))),
    (re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"), _fake_ip),
]


def redact(text: str, entities: dict | None = None) -> str:
    out = text
    # 1) known injected entities -> a plausible fake of the same type
    for kind, val in (entities or {}).items():
        val = str(val)
        if len(val) < 3 or kind == "country":
            continue
        fake = {"crew": _pick(_FAKE_HANDLES, val).lstrip("@"),
                "victim": _pick(_FAKE_DOMAINS, val),
                "handle": _pick(_FAKE_HANDLES, val)}.get(kind)
        if fake:
            out = re.sub(re.escape(val), fake, out, flags=re.IGNORECASE)
    # 2) structural pass for anything leaked/invented
    for pat, repl in _SUBS:
        out = pat.sub(repl, out)  # type: ignore[arg-type]
    return out


def load_real() -> list[dict]:
    blocks = [b.strip() for b in REAL.read_text(encoding="utf-8").split("---") if b.strip()]
    # data.md is a corpus of real incidents -> label 1. (Hand-curate exceptions later.)
    return [{"text": redact(b), "label": 1, "source": "real"} for b in blocks]


def load_syn(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        out.append({"text": redact(r["text"], r.get("entities")), "label": r["label"],
                    "source": "synthetic"})
    return out


def main() -> None:
    random.seed(0)
    real = load_real()
    # base synthetic + the extra link/handle-bearing hard negatives (if generated)
    syn = load_syn(SYN) + load_syn(HERE / "synthetic_neg_hard.jsonl")
    random.shuffle(real)
    k = max(1, round(len(real) * 0.30))
    test = real[:k]                      # locked held-out real
    train = real[k:] + syn              # redacted-real-train + all synthetic
    random.shuffle(train)

    for name, rows in (("train", train), ("test", test)):
        with open(HERE / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        pos = sum(x["label"] for x in rows)
        print(f"{name}: {len(rows)} rows ({pos} pos / {len(rows)-pos} neg)")
    print(f"  test = {k} held-out REAL positives (never trained)")
    print("\nsample redactions:")
    for r in test[:3]:
        print("  ", r["text"][:90].replace("\n", " "))


if __name__ == "__main__":
    main()
