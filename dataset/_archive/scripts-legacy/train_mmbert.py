#!/usr/bin/env python3
"""Fine-tune mmBERT-base (laya-multilingual's encoder) as a binary incident
classifier, and compare to zero-shot laya on the SAME held-out test.

Train: dataset/train.jsonl (redacted real + synthetic). Test: dataset/test.jsonl
(held-out real positives, never trained) + hand-authored benign negatives, all
redacted to match the training distribution. Reports AUROC for both.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ["USE_TF"] = "0"
import numpy as np  # noqa: E402
import torch  # noqa: E402
from datasets import Dataset  # noqa: E402
from transformers import (  # noqa: E402
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)

import build_dataset as bd  # noqa: E402  (redact)
import laya_eval as le  # noqa: E402  (hand-authored benign negatives)

HERE = Path(__file__).parent
BASE = "jhu-clsp/mmBERT-base"
OUT = str(HERE / "mmbert-incident")


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def auroc(pos: list[float], neg: list[float]) -> float:
    w = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return w / (len(pos) * len(neg)) if pos and neg else float("nan")


def build_test() -> tuple[list[str], list[int]]:
    pos = [r["text"] for r in load_jsonl(HERE / "test.jsonl")]
    neg = [bd.redact(t) for t in le.negatives]  # redact benign to match distribution
    texts = pos + neg
    labels = [1] * len(pos) + [0] * len(neg)
    return texts, labels


def zeroshot_laya(texts: list[str], labels: list[int]) -> float:
    from laya import Router  # noqa: PLC0415
    r = Router(preload=True)
    scores = []
    for t in texts:
        a = r.predict(t, le.QUESTION)["answers"]["incident"]
        scores.append(float(a["probabilities"]["A"]))
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    return auroc(pos, neg)


def main() -> None:
    tok = AutoTokenizer.from_pretrained(BASE)
    # Pool: synthetic + silver-harvested real, then GOLD human labels override any
    # duplicate (human truth wins). Keyed by redacted text so dups collapse.
    pool: dict[str, dict] = {}
    for p in ("train.jsonl", "real_train.jsonl"):
        for r in load_jsonl(HERE / p):
            pool[r["text"]] = r
    gold = HERE / "decision_log.labels.jsonl"
    if gold.exists():
        ng = 0
        for r in load_jsonl(gold):
            rt = bd.redact(r["text"])  # match the redaction used on train rows
            pool[rt] = {"text": rt, "label": r["label"], "source": "gold"}
            ng += 1
        print(f"folded {ng} gold human labels (override silver)")
    train = list(pool.values())
    rt = HERE / "real_test.jsonl"
    if rt.exists():
        rows = load_jsonl(rt)
        te_texts, te_labels = [r["text"] for r in rows], [r["label"] for r in rows]
    else:
        te_texts, te_labels = build_test()

    def tokz(batch):
        return tok(batch["text"], truncation=True, max_length=128)

    ds_tr = Dataset.from_list([{"text": r["text"], "label": r["label"]} for r in train]).map(
        tokz, batched=True
    )
    ds_te = Dataset.from_list(
        [{"text": t, "label": y} for t, y in zip(te_texts, te_labels)]
    ).map(tokz, batched=True)

    model = AutoModelForSequenceClassification.from_pretrained(BASE, num_labels=2)
    args = TrainingArguments(
        output_dir=OUT,
        num_train_epochs=4,
        per_device_train_batch_size=8,
        gradient_accumulation_steps=2,
        learning_rate=2e-5,
        warmup_steps=40,
        weight_decay=0.01,
        bf16=torch.cuda.is_available(),
        gradient_checkpointing=True,
        logging_steps=25,
        save_strategy="no",
        report_to=[],
    )
    trainer = Trainer(model=model, args=args, train_dataset=ds_tr, processing_class=tok)
    trainer.train()

    # Fine-tuned eval on the held-out test.
    model.eval()
    pred = trainer.predict(ds_te)
    probs = torch.softmax(torch.tensor(pred.predictions), dim=-1)[:, 1].numpy()
    pos = [float(p) for p, y in zip(probs, te_labels) if y == 1]
    neg = [float(p) for p, y in zip(probs, te_labels) if y == 0]
    ft_auroc = auroc(pos, neg)
    acc = float(np.mean([(p >= 0.5) == bool(y) for p, y in zip(probs, te_labels)]))

    print("\n" + "=" * 56)
    print(f"held-out test: {sum(te_labels)} pos / {len(te_labels)-sum(te_labels)} neg")
    zs = zeroshot_laya(te_texts, te_labels)
    print(f"  zero-shot laya AUROC   : {zs:.3f}")
    print(f"  fine-tuned mmBERT AUROC: {ft_auroc:.3f}   acc@.5={acc:.2f}")
    print(f"  mean P(inc): pos={np.mean(pos):.2f}  neg={np.mean(neg):.2f}")
    print("=" * 56)
    trainer.save_model(OUT)
    tok.save_pretrained(OUT)
    print(f"saved -> {OUT}")


if __name__ == "__main__":
    main()
