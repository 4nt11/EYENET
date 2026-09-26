"""Zero-shot laya eval for incident detection.

Positives = dataset/data.md cases. Negatives = hand-written benign multilingual
chatter (incl. a HARD negative: a news article ABOUT a hack — mentions a breach
but is not a threat actor bragging). Reports confidence separation + AUROC, and
cross-checks against the structural prefilter.

Gate on `confidence` (card: act_probability is broken, AUROC 0.30). Run on GPU.
"""

import os
import sys
import time

os.environ["USE_TF"] = "0"
sys.path.insert(0, "/home/anti/Projects/EYENET")

from pathlib import Path  # noqa: E402

from eyenet.incidents.prefilter import scan  # noqa: E402

DATA = Path("/home/anti/Projects/EYENET/dataset/data.md")
positives = [b.strip() for b in DATA.read_text(encoding="utf-8").split("---") if b.strip()]

# Benign negatives — none of these is a threat actor announcing/selling an intrusion.
negatives = [
    "Buenos días equipo, la reunión de sprint es a las 15:00, no falten.",
    "Кто-нибудь смотрел вчерашний матч? Счёт был безумный вчера.",
    "the printer at 192.168.1.20 is jammed again, someone reboot it pls",
    "great talk @conf_speaker! where can I find the slides from today?",
    "इस वीकेंड कोई अच्छी फिल्म देखने का प्लान है क्या?",
    "just deployed the new release to prod, db migration went fine 🎉",
    "This week's reads: https://blog.example.com/a https://blog.example.com/b",
    "dm @support if your invoice looks wrong, we'll sort it out",
    "anyone got the setup guide for the home lab? my nas keeps dropping",
    "喝杯咖啡休息一下，今天的会议太多了",
    # HARD negative: news article ABOUT a breach (not a brag).
    "BBC News: Hackers breached a UK council last week, leaking resident data. "
    "Officials said the database was exposed via a vulnerability. Police investigating.",
    # HARD negative: a pentester's authorized-engagement note.
    "finished the authorized pentest for client, found an SQLi, reported it, "
    "they patched it. writing up the CVE mapping now.",
]

# Two-option `choice` with neutral A/B labels — avoids the noul false:/true: label
# bias (laya GH #156). A = incident, B = not.
QUESTION = {
    "incident": {
        "type": "choice",
        "instructions": "Classify who wrote this message and why.",
        "criteria": {
            "A": (
                "the author is a threat actor claiming, boasting about, advertising, or "
                "selling a computer intrusion, website defacement, DDoS takedown, data "
                "breach, database or credential leak, stolen-data dump, infostealer logs, "
                "or unauthorized access they carried out or possess"
            ),
            "B": (
                "anything else: ordinary conversation, a news report about a hack, "
                "security research, or authorized penetration testing"
            ),
        },
    }
}


def p_yes(ans: dict) -> float:
    """P(incident=yes). laya's schema differs by type:
    - choice: real class probs live in `probabilities` ({'A':..,'B':..}); the
      top-level `confidence` is a margin, NOT P(A) — do not use it.
    - noul: the `noul` field IS P(true) directly."""
    probs = ans.get("probabilities")
    if isinstance(probs, dict) and "A" in probs:
        return float(probs["A"])
    if ans.get("type") == "noul" or "noul" in ans:
        return float(ans.get("noul", ans.get("confidence", 0.5)))
    choice = str(ans.get("choice", "")).lower()
    conf = float(ans.get("answer_confidence", ans.get("confidence", 0.5)))
    yes = choice in ("true", "yes", "1", "a", "incident", "positive")
    return conf if yes else 1.0 - conf


def auroc(scores_pos, scores_neg) -> float:
    wins = ties = 0
    for sp in scores_pos:
        for sn in scores_neg:
            if sp > sn:
                wins += 1
            elif sp == sn:
                ties += 1
    n = len(scores_pos) * len(scores_neg)
    return (wins + 0.5 * ties) / n if n else float("nan")


def main() -> None:
    from laya import Router  # type: ignore

    t0 = time.time()
    router = Router(preload=True)
    print(f"[laya] Router(preload=True) loaded in {time.time() - t0:.1f}s\n")

    # Inspect the raw schema once so we know the real keys.
    demo = router.predict(positives[0], QUESTION)
    print("RAW answer schema (first positive):", demo["answers"]["incident"], "\n")

    def run(texts):
        out = []
        t = time.time()
        for x in texts:
            r = router.predict(x, QUESTION)
            out.append(p_yes(r["answers"]["incident"]))
        return out, (time.time() - t) / max(len(texts), 1)

    pos_scores, pos_lat = run(positives)
    neg_scores, neg_lat = run(negatives)

    print(f"latency/case ~ {1000 * (pos_lat + neg_lat) / 2:.0f} ms\n")
    thr = 0.5
    tp = sum(s >= thr for s in pos_scores)
    fn = len(pos_scores) - tp
    tn = sum(s < thr for s in neg_scores)
    fp = len(neg_scores) - tn
    print(f"POS n={len(pos_scores)}  mean P(yes)={sum(pos_scores)/len(pos_scores):.3f}  recall@.5={tp}/{len(pos_scores)}")
    print(f"NEG n={len(neg_scores)}  mean P(yes)={sum(neg_scores)/len(neg_scores):.3f}  specificity@.5={tn}/{len(neg_scores)}")
    print(f"AUROC={auroc(pos_scores, neg_scores):.3f}  (1.0=perfect separation, 0.5=chance)\n")

    # Where does laya beat the prefilter? Positives the prefilter MISSED but laya caught.
    print("=== laya vs prefilter on positives (prefilter MISS -> laya says?) ===")
    for x, s in zip(positives, pos_scores):
        if not scan(x).adjudicate:
            head = x.replace("\n", " ")[:60]
            mark = "laya YES ✅" if s >= thr else "laya no  ❌"
            print(f"  {mark} p={s:.2f} | {head}")

    print("\n=== negatives laya got WRONG (false positives) ===")
    for x, s in zip(negatives, neg_scores):
        if s >= thr:
            print(f"  FP p={s:.2f} | {x[:70]}")


if __name__ == "__main__":
    main()
