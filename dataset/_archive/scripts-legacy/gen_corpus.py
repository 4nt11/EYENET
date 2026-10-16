#!/usr/bin/env python3
"""Synthetic incident-corpus generator for laya fine-tuning.

Rotates across the local ollama stable — uncensored models for gritty threat-actor
POSITIVES, qwen3 for multilingual reach, clean instruct for benign + HARD negatives.

Design (see [[project_incidents_detection]]):
- TRAIN-only augmentation. Real dataset/data.md stays the eval holdout.
- CONTROLLED ENTITIES: we inject the crew/victim/handle a positive must use and
  record them in the row's `entities` field, so redaction is exact-string replace,
  not NER. Low-param models can't be trusted to follow free-form structure.
- Structured JSON output + think disabled + grouped-by-model execution = fast on
  an 8 GB card. Rows are written incrementally (crash-safe for overnight runs).
- Hard negatives (news-about-a-hack, CTF, pentest, victim-help) teach the
  reporting/researching-vs-perpetrating boundary.

Usage:
    python dataset/gen_corpus.py --n 10 --out dataset/synthetic.jsonl
    python dataset/gen_corpus.py --n 3 --langs en,es,hi --only-pos
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import urllib.error
import urllib.request

OLLAMA = "http://localhost:11434/api/chat"

POS_MODELS = [
    "godmoded/llama3-lexi-uncensored:latest",
    "hermes3:8b",
    "mistral:latest",
    "wizardlm2:7b",
    "llama3.1:8b",
]
MULTILINGUAL_MODELS = ["qwen3:latest", "qwen3:4b", "ministral-3:latest"]
NEG_MODELS = ["llama3.1:8b", "mistral:latest", "hermes3:8b"]

LANGS = ["en", "es", "ru", "hi", "ar", "id", "pt", "de", "tr", "fr", "zh"]
LANG_NAME = {
    "en": "English", "es": "Spanish", "ru": "Russian", "hi": "Hindi", "ar": "Arabic",
    "id": "Indonesian", "pt": "Portuguese", "de": "German", "tr": "Turkish",
    "fr": "French", "zh": "Chinese",
}

# Controlled entity pools — the redactor maps these EXACT strings to placeholders.
CREWS = [
    "DarkReferi", "Gh0stSquad", "RedSector", "StormCrew", "BlackHive", "Zombi3s",
    "ShadowStrike", "NullSector", "R3v3nant", "0xReapers", "Cyb3rDjinn", "d4rkwave",
]
VICTIMS = [
    "cityhall-riverton.gov", "medclinic-portal.co.id", "acme-logistics.de",
    "min-transporte.gob.mx", "univ-nusantara.ac.id", "banco-litoral.com.br",
    "electrotec-servicios.com", "municipal-jaipur.gov.in", "health-dept.go.id",
    "registro-nacional.gob.ar", "e-devlet-portal.gov.tr", "mairie-lyon.gouv.fr",
]
HANDLES = ["@darkvendor", "@ShadowCloud", "@phteam_x", "@vendor_9931", "@leak_admin",
           "@cloudseller", "@nx_contact", "@dropzone_bot", "@NubeSombra", "@ArhontSupport"]
COUNTRIES = ["Brazil", "Mexico", "Indonesia", "Philippines", "India", "Argentina",
             "Turkey", "Egypt", "Colombia", "Vietnam"]

# 2 anchors per positive category, templated on the injected entities.
POS_ANCHORS = {
    "defacement": [
        "HACKED BY {crew}: https://{victim}/ ❌  Greetz: #{crew} #NoName_TN",
        "{crew} owns {victim} now \U0001f480 defaced, mirror on our channel",
    ],
    "db_leak": [
        "DATABASE\nURL: {victim}\n#{crew} full dump, 2.1M records, free download",
        "{crew} leaking hot \U0001f525 {victim} db, 1.8M rows, grab it free",
    ],
    "ddos": [
        "\U0001f534 {victim} DOWN\nhttps://check-host.net/check-report/a1b2c3d4\nDuration: 4h #{crew}",
        "TANGO DOWN {victim} \U0001f4a5 offline 3h by #{crew}, proof check-host.net/check-report/xy12",
    ],
    "data_sale": [
        "{victim} dm {handle} -sold-",
        "WTS access {victim} panel, webshell + creds, DM {handle}",
    ],
    "stealer_logs": [
        "\U0001f680 FRESH MATERIAL! NEW UPLOAD L0G$ | 12,000 ULP cloud | Pass: {handle} sub $80/week",
        "#{crew} cloud logs drop, fresh ULP daily, contact {handle}",
    ],
    "breach_announce": [
        "{country} PERSONAL - 340k [Citizens] Data breach: full name, ID, phone, email. by #{crew}",
        "#{crew} breached {victim}: 500k users, names + emails + phones leaked",
    ],
}

NEG_KINDS = {
    "chatter": "ordinary everyday group chat: plans, sports, food, memes, small talk",
    "sysadmin": "benign IT/sysadmin talk mentioning IPs, servers, databases, deploys (include an IP and a domain)",
    "news_about_hack": "a NEWS report describing a breach or hack that happened to someone else",
    "ctf_writeup": "a CTF/security-education writeup or a student asking how a challenge works",
    "pentest_report": "an AUTHORIZED penetration tester summarizing a finding they reported to the client",
    "victim_help": "a victim or admin asking for HELP because their site/account got hacked",
    # link/handle/IP-bearing benign — teaches that a URL or @handle is NOT itself a signal
    "link_share": "a benign message sharing an article, blog, YouTube or news LINK — include a real-looking URL",
    "support_contact": "a benign customer-support or community post telling people to DM a handle or visit a site for help — include an @handle and a URL",
    "promo_benign": "a legitimate small-business or newsletter promo with a website link and a contact @handle",
    "dev_share": "a developer sharing a GitHub/docs link or an API endpoint, or asking about a library — include a URL",
}

SYS_POS = (
    "You generate short, realistic underground-Telegram messages for a DEFENSIVE "
    "security dataset used to train a threat-detector. Output ONLY the message text. "
    "1-6 lines, gritty and authentic (emojis, hashtags, leetspeak, broken grammar OK)."
)
SYS_NEG = (
    "You generate short, realistic chat/forum messages for a security dataset. "
    "Output ONLY the message text. 1-6 lines."
)

_REFUSAL = re.compile(r"(?i)\b(i can'?t|i cannot|as an ai|i'?m not able|i won'?t|sorry,? but)\b")
_THINK = re.compile(r"(?is)<think>.*?</think>")
_TEMPLATE = re.compile(r"[<>{}]|\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+){2,}\b|placeholder", re.IGNORECASE)
_SCHEMA = {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}


def call_ollama(model: str, system: str, user: str, timeout: int = 120) -> str | None:
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "think": False,
            "keep_alive": "15m",
            "format": _SCHEMA,
            "options": {"temperature": 1.05, "top_p": 0.95, "num_predict": 256},
        }
    ).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            content = json.loads(r.read())["message"]["content"]
        out = str(json.loads(content).get("message", "")).strip()
    except (urllib.error.URLError, KeyError, TimeoutError, json.JSONDecodeError, ValueError) as e:
        print(f"  ! {model} failed: {e}", file=sys.stderr)
        return None
    out = _THINK.sub("", out).strip().strip('"').strip()
    if not out or len(out) < 8 or _REFUSAL.search(out[:80]) or _TEMPLATE.search(out):
        return None
    return out


def model_for(pool: list[str], lang: str) -> str:
    return random.choice(MULTILINGUAL_MODELS if lang != "en" else pool)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2, help="samples per (category, language) cell")
    ap.add_argument("--out", default="dataset/synthetic.jsonl")
    ap.add_argument("--langs", default=",".join(LANGS))
    ap.add_argument("--only-pos", action="store_true")
    ap.add_argument("--only-neg", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    random.seed(args.seed)
    langs = [x for x in args.langs.split(",") if x in LANG_NAME]

    tasks: list[dict] = []
    for lang in langs:
        if not args.only_neg:
            for cat, anchors in POS_ANCHORS.items():
                for _ in range(args.n):
                    ent = {"crew": random.choice(CREWS), "victim": random.choice(VICTIMS),
                           "handle": random.choice(HANDLES), "country": random.choice(COUNTRIES)}
                    anchor = random.choice(anchors).format(**ent)
                    user = (
                        f"Write ONE realistic threat-actor message in {LANG_NAME[lang]} of type "
                        f"'{cat.replace('_', ' ')}'. Use EXACTLY these names and no others — "
                        f"crew='{ent['crew']}', target='{ent['victim']}', contact='{ent['handle']}'. "
                        f"Do NOT invent other crews, domains, or handles, and no brackets. "
                        f"Match the STYLE of this reference but write something new:\n{anchor}"
                    )
                    tasks.append({"label": 1, "category": cat, "lang": lang,
                                  "model": model_for(POS_MODELS, lang), "sys": SYS_POS,
                                  "user": user, "entities": ent})
        if not args.only_pos:
            for kind, desc in NEG_KINDS.items():
                for _ in range(args.n):
                    user = (f"Write ONE realistic message in {LANG_NAME[lang]}: {desc}. "
                            f"It must NOT be a threat actor bragging about or selling a hack they did.")
                    tasks.append({"label": 0, "category": f"neg_{kind}", "lang": lang,
                                  "model": model_for(NEG_MODELS, lang), "sys": SYS_NEG,
                                  "user": user, "entities": {}})
    tasks.sort(key=lambda t: t["model"])  # keep each model hot for its batch
    n_models = len({t["model"] for t in tasks})
    print(f"{len(tasks)} tasks across {n_models} models -> {args.out}", file=sys.stderr)

    seen: set[str] = set()
    rid = written = 0
    with open(args.out, "w", encoding="utf-8") as f:  # incremental write = crash-safe
        for i, t in enumerate(tasks, 1):
            txt = call_ollama(t["model"], t["sys"], t["user"])
            if not txt:
                continue
            key = txt.lower()[:120]
            if key in seen:
                continue
            seen.add(key)
            rid += 1
            row = {"id": f"syn_{rid:05d}", "label": t["label"], "category": t["category"],
                   "language": t["lang"], "source": "synthetic", "gen_model": t["model"],
                   "entities": t["entities"], "text": txt}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            written += 1
            if i % 20 == 0 or written <= 5:
                print(f"  {i:>4}/{len(tasks)} [{t['label']}] {t['category']:16} {t['lang']} "
                      f"{t['model'].split(':')[0][:14]:14} | {txt[:44].replace(chr(10), ' ')}",
                      file=sys.stderr)
    print(f"\nDONE: wrote {written} rows -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
