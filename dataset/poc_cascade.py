#!/usr/bin/env python3
"""PoC: the full 3-stage incident-detection cascade on the real corpus (data.md).
Not production code — a demo of the tiered engine.

Stage 1  prefilter.scan()  cheap structural gate (RE2)          -> signals
Stage 2  laya (choice Q)    calibrated multilingual read        -> P(incident)
Stage 3  qwen (ollama)      cheap LLM tiebreaker, ONLY for laya's uncertain band

Routing: laya decides the confident cases for free. Only LOW < P < HIGH (or a
prefilter/laya conflict) escalates to the LLM. Most messages never reach stage 3.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

os.environ["USE_TF"] = "0"
sys.path.insert(0, "/home/anti/Projects/EYENET")
from eyenet.incidents.prefilter import scan  # noqa: E402

HERE = Path(__file__).parent
HIGH, LOW = 0.65, 0.40          # laya-confident thresholds; between them -> LLM
LLM_MODEL = "qwen3:4b"
OLLAMA = "http://localhost:11434/api/chat"

QUESTION = {
    "incident": {
        "type": "choice",
        "instructions": "Classify who wrote this message and why.",
        "criteria": {
            "A": ("the author is a threat actor claiming, boasting about, advertising, or "
                  "selling a computer intrusion, defacement, DDoS, data breach, database or "
                  "credential leak, stolen-data dump, infostealer logs, or unauthorized access"),
            "B": "anything else: ordinary conversation, news, security research, or authorized testing",
        },
    }
}

# reason BEFORE verdict — structured output fills fields in order, so this forces
# the model to analyse first and decide second (chain-of-thought), instead of
# committing to a blind boolean it then rationalises.
_LLM_SCHEMA = {"type": "object",
               "properties": {"reason": {"type": "string"}, "incident": {"type": "boolean"}},
               "required": ["reason", "incident"]}

# What each prefilter signal MEANS — concrete evidence for the LLM to weigh, not
# just an opaque tag. Only the discriminative ones need a gloss.
SIGNAL_DESC = {
    "deface_banner": "a defacement banner ('HACKED BY', 'Greetz', 'defaced by')",
    "check_host": "a check-host.net proof-of-downtime link (DDoS 'tango down' evidence)",
    "cloud_pass": "a stealer-cloud channel password ('Pass: @channel')",
    "stealer_logs": "infostealer-log/combolist terms (ULP, fresh logs, L0G$)",
    "sale_marker": "a data/access sale marker ('-sold-', 'WTS', 'for sale')",
    "access_material": "access-for-sale material (webshell, RDP, root/admin access)",
    "leak_label": "a leak/breach label ('DATABASE', 'data breach', 'registros')",
    "leak_host": "a leak-drop or breach-forum host (pastebin, mega, darkforums)",
    "cred_combo": "an email:password credential pair",
    "cred_label": "a User:/Pw: credential dump",
    "pii_schema": "a leaked PII column schema (name, passport, dob, phone)",
    "session_id": "a Session Messenger contact id (buyer contact)",
    "target_dump_file": "a dump file named after a victim domain",
    "multi_target": "a list of 3+ attack targets (URLs or IPs)",
    "crew_tag_cluster": "a cluster of crew hashtags (a shoutout)",
    "institutional_target": "a government / military / education victim domain",
    "onion_url": "a .onion dark-web mirror",
    "hash_list": "a dumped list of password hashes",
    "record_count": "a record-count boast (e.g. '2M records')",
    "dm_contact": "a 'DM @handle' contact-to-transact",
    "tg_target": "a @handle or t.me link",
}


def llm_judge(text: str, signals: tuple[str, ...], laya_p: float) -> tuple[bool, str]:
    sys_p = (
        "You triage messages from monitored hacker channels. Output a one-sentence `reason` "
        "FIRST, then the boolean `incident`.\n\n"
        "Ask ONE question: is the AUTHOR the perpetrator/seller/broker of an attack?\n\n"
        "incident = true when the author is:\n"
        "- claiming a hack/defacement ('hacked by X', 'X defaced', 'owned', 'got root')\n"
        "- announcing/sharing a leak or dump (database, credentials, PII, combolist)\n"
        "- selling or brokering data/access ('-sold-', 'WTS', 'DM to buy', 'price')\n"
        "- dropping/advertising stealer logs ('fresh ULP', 'cloud logs', 'pass: @channel')\n"
        "- claiming a DDoS/takedown ('tango down', 'DOWN', check-host proof)\n"
        "- offering or coordinating an intrusion ('webshell', 'shell access', 'join the attack')\n\n"
        "incident = false ONLY for:\n"
        "- NEWS/journalism describing someone else's breach\n"
        "- security research, CTF write-ups, or an AUTHORIZED pentest report\n"
        "- a victim/admin asking for help after being hacked\n"
        "- ordinary chat, or a benign link/@handle/promo (a URL alone is NOT a signal)\n\n"
        "Examples:\n"
        "'victim.tld dm @seller -sold-' -> true (selling access)\n"
        "'STANFORD UNIVERSITY DEFACED! http://...' -> true (defacement claim)\n"
        "'9.7 millones de registros de ciudadanos' -> true (leaked PII)\n"
        "'BBC: hackers breached a council last week' -> false (news)\n"
        "'finished the authorized pentest, reported the SQLi' -> false (authorized)\n"
        "'dm @support if your invoice looks wrong' -> false (benign support)\n\n"
        "If it fits a `true` category at all, answer true. Only answer false when it clearly "
        "matches a false category. A missed attack costs more than an operator review."
    )
    if signals:
        ev = "; ".join(SIGNAL_DESC.get(s, s) for s in signals)
        context = (f"Structural detectors already flagged: {ev}. "
                   "The semantic model was UNCERTAIN, so this needs your call. "
                   "Weigh that evidence, but judge from the message content.")
    else:
        context = ("No structural attack indicators fired, and the semantic model was "
                   "UNCERTAIN. Judge purely from the message content.")
    usr = f"{context}\n\nMessage:\n{text[:3000]}"
    body = json.dumps({"model": LLM_MODEL,
                       "messages": [{"role": "system", "content": sys_p}, {"role": "user", "content": usr}],
                       "stream": False, "think": False, "keep_alive": "10m", "format": _LLM_SCHEMA,
                       "options": {"temperature": 0.2}}).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            d = json.loads(json.loads(r.read())["message"]["content"])
        return bool(d.get("incident")), str(d.get("reason", ""))[:60]
    except Exception as e:  # noqa: BLE001 (PoC)
        return laya_p >= 0.5, f"llm-error:{type(e).__name__}"


def main() -> None:
    from laya import Router  # noqa: PLC0415

    blocks = [b.strip() for b in (HERE / "data.md").read_text(encoding="utf-8").split("---") if b.strip()]
    router = Router(preload=True)

    by = {"prefilter/laya": 0, "laya": 0, "llm": 0}
    flagged = escalated = 0
    print(f"{'#':>3}  {'PREFILTER':<20} {'LAYA':>5} {'STAGE':>6}  VERDICT  message")
    print("-" * 104)
    for i, b in enumerate(blocks):
        pf = scan(b)
        p = float(router.predict(b, QUESTION)["answers"]["incident"]["probabilities"]["A"])
        note = ""
        if p >= HIGH:
            inc, stage = True, "laya"
            by["laya" if not pf.adjudicate else "prefilter/laya"] += 1
        elif p < LOW and not pf.adjudicate:
            inc, stage = False, "laya"
            by["laya"] += 1
        else:                                   # uncertain middle OR prefilter/laya conflict
            inc, reason = llm_judge(b, pf.signals, p)
            stage, escalated = "llm", escalated + 1
            by["llm"] += 1
            note = f"  ↳ qwen: {'YES' if inc else 'no'} ({reason})"
        flagged += inc
        head = b.replace("\n", " ")[:40]
        mark = "🚨" if inc else "  "
        print(f"{i:>3}  {(','.join(pf.signals[:2]) or '-'):<20} {p:>5.2f} {stage:>6}  {mark}{'INC' if inc else 'clr':<4} {head}")
        if note:
            print(note)

    n = len(blocks)
    print("-" * 104)
    print(f"\n{flagged}/{n} flagged incidents | {escalated}/{n} needed the LLM (stage 3)")
    print(f"  decided by prefilter+laya (free): {n - escalated}")
    print(f"  escalated to qwen (uncertain)   : {escalated}")


if __name__ == "__main__":
    main()
