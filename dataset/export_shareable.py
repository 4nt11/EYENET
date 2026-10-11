#!/usr/bin/env python3
"""Export gold_v2 as a shareable, anonymized incident dataset.

The v2 human-reviewed gold (dataset/gold_v2.mllabels.jsonl) is the set the
16-head mmBERT classifier trains its GOLD slice on. This turns it into something
safe to hand out:

  1. bd.redact  -> opsec/domain identifiers (@handles, domains, URLs, crypto)
                   swapped for plausible FAKES of the same type (label-neutral).
  2. Presidio   -> two passes (en + es) tag any remaining PII (names, emails,
                   phones, locations, ...) as <ENTITY_TYPE>.

Nothing is deleted: every value is REPLACED, so register/structure survive and
the labels stay valid. Labels are emitted as the canonical 16-leaf vector so the
file matches the classifier's own view. `tier` is carried through
(reviewed | ai | rescued) so consumers can filter to the human-only slice.

The attachment signal the model actually trains on (enrich_text appends the filename)
is joined in from the corpus so the share is reproducible, NOT half the input:
`has_attachment` (bool), `att_kinds`, and `att_files` with filenames scrubbed the same
way as bodies (target domains stripped, extension kept).

Run (needs the project venv with presidio + spaCy es/en models):
    .venv/bin/python dataset/export_shareable.py
Self-check:
    .venv/bin/python dataset/export_shareable.py --selftest

Out: dataset/gold_v2.shareable.jsonl   ({text, labels:[16 floats], tier})
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

import build_dataset as bd  # noqa: E402  (canonical opsec redactor -> fakes, not tags)

HERE = Path(__file__).parent
SRC = HERE / "gold_v2.mllabels.jsonl"
CORPUS = HERE / "eyenet_messages.jsonl"  # source of the attachment signal (has_attachment/att_files)
OUT = HERE / "gold_v2.shareable.jsonl"

# Hand-scrubbed one-row overrides, keyed by sha1 of the RAW text. For rows whose PII is
# free-form (company names + non-standard street addresses) that no automated pass can
# reliably target. The column STRUCTURE (the breach_dump signal) is preserved; every real
# value becomes a type tag. Applied verbatim in place of scrub() for the matching raw row.
_ROW_OVERRIDES = {
    # row 902: leaked "MAS KARGO" logistics-CRM customer export (::-delimited)
    "2170624f37cf1b8322d27763a9ce473f7fab3aa4": "\n".join(
        [
            "<ORGANIZATION> ( COLLECT )::<ID>::<ADDRESS>, Jakarta, INDONESIA::<PHONE_NUMBER>::<PERSON>::<EMAIL_ADDRESS>::<PERSON>::<ORGANIZATION> JAKARTA",
            "<ORGANIZATION> ( Jakarta )::<ID>::<ADDRESS>, INDONESIA::<PHONE_NUMBER>::-::-::<PERSON>::<ORGANIZATION> JAKARTA",
            "<ORGANIZATION>::<ID>::<ADDRESS>, INDONESIA::<PHONE_NUMBER>::.::<EMAIL_ADDRESS>::<PERSON>::<ORGANIZATION> JAKARTA",
            "<ORGANIZATION>::<ID>::<ADDRESS>, INDONESIA::<PHONE_NUMBER>::<PERSON>::-::<PERSON>::<ORGANIZATION> BANDUNG",
            "<ORGANIZATION>::<ID>::<ADDRESS>, Jakarta, INDONESIA::<PHONE_NUMBER>::<PERSON>::-::<PERSON>::<ORGANIZATION> JAKARTA",
            "<ORGANIZATION>::<ID>::<ADDRESS>, Jakarta, INDONESIA::<PHONE_NUMBER>::<PERSON>::-::<PERSON>::<ORGANIZATION> JAKARTA",
            "<ORGANIZATION>::<ID>::<ADDRESS>, Jakarta, INDONESIA::<PHONE_NUMBER>::<PERSON>::-::<PERSON>::<ORGANIZATION> JAKARTA",
            "<ORGANIZATION>::<ID>::<ADDRESS>, Jakarta, INDONESIA::<PHONE_NUMBER>::-::-::<PERSON>::<ORGANIZATION> JAKARTA",
            "<ORGANIZATION>::<ID>::<ADDRESS>, Surabaya, INDONESIA::<PHONE_NUMBER>::<PERSON>::-::<PERSON>::<ORGANIZATION> SURABAYA",
            "<ORGANIZATION>::<ID>::<ADDRESS>, Jakarta, INDONESIA::<PHONE_NUMBER>::-::-::<PERSON>::<ORGANIZATION> JAKARTA",
        ]
    ),
}

# Presidio runs ONLY these high-precision structured identifiers. The noisy NER
# categories (PERSON/ORGANIZATION/LOCATION/URL/DATE_TIME/NRP) are deliberately OFF:
# in a threat-actor corpus they ARE the signal (crew names, target country,
# "Leaked by"), and letting spaCy tag them erodes the dataset. bd.redact already
# owns URLs/domains/handles/crypto/IPs (structure-preserving fakes); the credential
# pass below owns user/pass pairs. What's left for Presidio is genuinely-PII structure
# that bd does not touch: bare emails, phones, cards, IBANs, SSNs.
PII_ENTITIES = ["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "IBAN_CODE", "US_SSN"]
# Extra NER for DUMP-LIKE rows only (victim-record / CRM-leads exports). Those rows are pure
# PII payload with no crew-name signal to protect, so PERSON/LOCATION/ORG tagging that would
# erode a normal brag row is safe -- and necessary to catch free-form names/street addresses
# that no structured pass can. Applied only when a row looks like a bulk PII dump.
PII_ENTITIES_DUMP = PII_ENTITIES + ["PERSON", "LOCATION", "NRP", "ORGANIZATION"]


def _is_dump_row(text: str) -> bool:
    """A row is a bulk-PII dump if it already carries several redaction markers or many
    '::'-delimited fields -- i.e. a victim/leads export, not a single-incident brag."""
    markers = text.count("cred_") + text.count("<EMAIL_ADDRESS>") + text.count("<PHONE_NUMBER>")
    return markers >= 4 or text.count("::") >= 3

# user/pass/login pairs in defacement brags. bd only catches inline email:pass, not
# standalone "PASSWORD : xxx" lines. Multilingual label words; value is the capture.
# NO \b: actors glue fields ("gmail.comPASSWORD: x") and \b won't fire between letters,
# so a boundary requirement leaks the value. Slight over-match (e.g. "compass:") is a
# safe direction for an anonymizer.
_CRED_LABEL = re.compile(
    r"(?i)(?:user(?:name)?|pass(?:word)?|login|pwd|pin|senha|clave|usuario|contrase[nñ]a)"
    r"\s*[:=]\s*(\S{2,64})"
)

# Email with an OPTIONAL glued/spaced password (combo-list / stealer-log format:
# "foo@bar.com:Tiger358"). Atomic: the domain is matched greedily and the password is a
# single optional group, so there is NO backtracking-truncation (the old lookahead form
# matched ".co" to satisfy a lookahead and stranded "m:password"). Group 1 = the secret.
_EMAIL_CRED = re.compile(
    r"[\w.+-]{2,64}@[\w-]{1,63}(?:\.[\w-]{2,24})+(?:\s*[:|]\s*([^\s|]{1,64}))?"
)

# Labeled PII fields in breach victim records ("Full Name: X | Phone: Y | Address: Z").
# Value runs to the next | or newline (addresses/phone-lists contain commas). High
# precision: only fires on an explicit field label, so crew handles/nicknames are untouched.
_PII_FIELD = re.compile(
    r"(?i)\b(full\s?name|name|nombre|apellido|address|direcci[oó]n|phone|tel[eé]fono|"
    r"mobile|m[oó]vil|dob|date\s?of\s?birth|birth|ssn|dni|nif|passport|pasaporte)\b"
    r"\s*[:=]\s*([^|\n]{2,80})"
)
_FIELD_TAG = {
    "name": "<PERSON>", "full name": "<PERSON>", "fullname": "<PERSON>",
    "nombre": "<PERSON>", "apellido": "<PERSON>",
    "address": "<ADDRESS>", "dirección": "<ADDRESS>", "direccion": "<ADDRESS>",
    "phone": "<PHONE_NUMBER>", "teléfono": "<PHONE_NUMBER>", "telefono": "<PHONE_NUMBER>",
    "mobile": "<PHONE_NUMBER>", "móvil": "<PHONE_NUMBER>", "movil": "<PHONE_NUMBER>",
    "dob": "<DATE_TIME>", "date of birth": "<DATE_TIME>", "birth": "<DATE_TIME>",
    "ssn": "<US_SSN>", "dni": "<ID>", "nif": "<ID>", "passport": "<ID>", "pasaporte": "<ID>",
}

# Phone / long digit runs glued into combo rows (7-15 digits, optional + and separators).
# Runs AFTER bd (bd's fake IPs are dotted, so this dash/space pattern won't touch them).
_PHONE = re.compile(r"\+?\d[\d][\d\-\s]{5,15}\d")


# Stealer-log / combo-list line: a LOCATOR (url, email, dotted-domain[/path], or 6+ digit
# phone) followed by 1-5 colon-joined credential tokens, as the WHOLE line. Line-anchored
# and space-free after the head, so prose ("e.g: some text here") can't match. The locator
# is kept (bd fakes a domain, _PHONE handles a numeric head); every cred token is killed.
_COMBO_LINE = re.compile(
    r"^(?P<head>https?://[^\s:|]+|[\w.+-]+@[\w.-]+|[\w-]+(?:\.[\w-]+)+(?:/[^\s:|]*)?|\+?\d{6,})"
    r"(?P<creds>(?::[^\s:|]{1,80}){1,5})\s*$",
    re.MULTILINE,
)

# Token-level combo scrub for lines that pack MANY space-separated credential tokens
# (row 655: "user:pass email@x:pass user2:pass2 ..."). A colon-token counts as a credential
# unless it's a clock time or a URL scheme. A line is treated as a dump ONLY if it holds >=2
# such tokens OR an email:pass token, so timestamp/prose lines ("End Time: 14:30") are safe.
_TIME = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")
_SCHEME = re.compile(r"^(?:https?|ftp)$", re.IGNORECASE)
_DOMAINISH = re.compile(r"^[\w-]+(?:\.[\w-]+)+(?:/\S*)?$")

# Indonesian CRM-leads dump (row 902, "::"-delimited): honorific-prefixed contact names and
# Jalan street addresses that no labeled-field/combo pass catches.
_HONORIFIC = re.compile(
    r"(?i)\b(?:Bpk|Bapak|Ibu|Pak|Sdr|Sdri|Mba|Mbak)\.?\s+[A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)?"
)
_STREET = re.compile(r"(?i)\bJl\.?\s*[^\n:|]{2,40}")


def _looks_cred_token(tok: str) -> bool:
    if ":" not in tok or _TIME.match(tok):
        return False
    parts = [p for p in tok.split(":") if p]
    if len(parts) < 2 or _SCHEME.match(parts[0]):
        return False
    return len(tok) >= 6 and any(c.isalpha() for p in parts for c in p)


def _redact_cred_token(tok: str) -> str:
    out = []
    for i, p in enumerate(tok.split(":")):
        if not p:
            out.append(p)
        elif "@" in p:
            out.append("<EMAIL_ADDRESS>")
        elif i == 0 and (_DOMAINISH.match(p) or p.isdigit()):
            out.append(p)  # locator kept: domain (bd fakes) or number (_PHONE tags)
        else:
            out.append(_fake_secret(p))  # bare username / password
    return ":".join(out)


def scrub_combo_lines(text: str) -> str:
    """Redact space-separated credential tokens on dump lines. ponytail: whitespace-run
    collapse on those lines only (payload lines); prose spacing elsewhere is untouched."""
    lines = []
    for line in text.split("\n"):
        toks = line.split()
        creds = [t for t in toks if _looks_cred_token(t)]
        if len(creds) >= 2 or any("@" in t for t in creds):
            lines.append(" ".join(_redact_cred_token(t) if t in creds else t for t in toks))
        else:
            lines.append(line)
    return "\n".join(lines)


def scrub_sensitive(text: str) -> str:
    """Deterministic PII passes for breach/combo/stealer-log rows, BEFORE bd + Presidio."""
    def _field(m: re.Match[str]) -> str:
        label = re.sub(r"\s+", " ", m.group(1).strip().lower())
        return f"{m.group(1)}: {_FIELD_TAG.get(label, '<REDACTED>')}"

    def _email(m: re.Match[str]) -> str:
        return "<EMAIL_ADDRESS>:" + _fake_secret(m.group(1)) if m.group(1) else "<EMAIL_ADDRESS>"

    def _combo(m: re.Match[str]) -> str:
        out = m.group("head")
        for tok in m.group("creds").split(":")[1:]:
            if not tok or tok.startswith("cred_") or tok.startswith("<"):
                out += f":{tok}"
            elif "@" in tok:
                out += ":<EMAIL_ADDRESS>"
            else:
                out += f":{_fake_secret(tok)}"
        return out

    def _labeled(m: re.Match[str]) -> str:
        val = m.group(2)
        return m.group(1) + ("<EMAIL_ADDRESS>" if "@" in val else _fake_secret(val))

    out = scrub_creds(text)          # user/pass/login: value  (glue-tolerant)
    out = _LABELED_CRED.sub(_labeled, out)  # USR - / PW - / PWD - dash template
    out = _PII_FIELD.sub(_field, out)  # Full Name / Phone / Address / DOB ...
    out = _HONORIFIC.sub("<PERSON>", out)  # Bpk./Ibu/Pak <Name> (CRM leads)
    out = _STREET.sub("<ADDRESS>", out)    # Jl. <street> (CRM leads)
    out = scrub_combo_lines(out)       # space-separated user:pass token blocks
    out = _COMBO_LINE.sub(_combo, out)  # stealer-log URL:USER:PASS triples (single-locator)
    out = _EMAIL_CRED.sub(_email, out)  # remaining standalone email(:pass)
    return out

# URL slug preservation. Some rows are ONLY a forum thread URL whose descriptive slug
# (database-icpo-interpol..., warga-israel) IS the evidence. bd.redact fakes the whole
# URL and destroys it. We lift the readable slug words out as plain text BEFORE bd fakes
# the host; Presidio then still scrubs any real name inside the slug.
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_SLUG_SPLIT = re.compile(r"[/\-_.?=&+%]+")
_SLUG_STOP = {
    "threads", "thread", "members", "member", "login", "index", "php", "html",
    "htm", "profile", "user", "users", "posts", "post", "forum", "forums",
    "view", "viewtopic", "showthread", "topic", "www", "http", "https",
}


def preserve_url_slugs(text: str) -> str:
    """Prepend a URL's human-readable path words as text so the signal survives bd faking
    the host. Drops structural words, numeric thread-ids, and long hex/hash tokens."""
    from urllib.parse import urlsplit

    def repl(m: re.Match[str]) -> str:
        u = m.group(0)
        parts = urlsplit(u)
        words = [
            w for w in _SLUG_SPLIT.split(f"{parts.path} {parts.query}")
            if len(w) >= 3 and not w.isdigit() and w.lower() not in _SLUG_STOP
            and not re.fullmatch(r"[0-9a-f]{16,}", w, re.IGNORECASE)
        ]
        return f"[{' '.join(words)}] {u}" if words else u

    return _URL.sub(repl, text)


# Breach-announcement template with labeled lines and a DASH separator:
#   USR - <username>   /   PW  - <password>   /   PWD - <password>
# Line-anchored so only whole label lines match (not inline prose). URL is intentionally
# excluded -- that line is the target (signal); bd fakes its host, slug-preserve keeps it.
_LABELED_CRED = re.compile(
    r"(?im)^([ \t]*(?:usr|user(?:name)?|pw|pwd|pass(?:word)?|login|pin)[ \t]*[-:=][ \t]*)"
    r"(\S.*?)[ \t]*$"
)


def _fake_secret(val: str) -> str:
    """Deterministic neutral stand-in. Keeps the 'PASSWORD: <x>' structure (the cred-dump
    signal) while killing the real value; no distinctive tag that would leak the label."""
    h = int(hashlib.md5(val.encode()).hexdigest(), 16)  # noqa: S324 (non-crypto)
    return f"cred_{h % 10000:04d}"


def scrub_creds(text: str) -> str:
    """Redact user/pass values. Finds them in an NFKD-normalized view so fancy-unicode
    labels (𝖴𝖲𝖤𝖱𝖭𝖠𝖬𝖤 : ...) are caught, then literal-replaces the value in the ORIGINAL
    so the actor's stylistic font choice (a stylometry signal) survives.
    ponytail: assumes the secret VALUE is ascii-ish (usernames/passwords are typed);
    a secret written in exotic unicode slips. Upgrade: NFKD the whole corpus if seen."""
    norm = unicodedata.normalize("NFKD", text)
    secrets = {m.group(1) for m in _CRED_LABEL.finditer(norm)}
    out = text
    for s in sorted(secrets, key=len, reverse=True):  # longest first: no substring clobber
        if s and s in out:
            out = out.replace(s, _fake_secret(s))
    return out

# ponytail: frozen v2 taxonomy, hardcoded to avoid importing the torch-heavy
# trainer just to read a list. Must stay identical to train_mmbert_ml.LABELS /
# bootstrap_silver.LABELS (single order, persisted to the model's labels.json).
LABELS = [
    "defacement", "ddos_attack", "intrusion",
    "breach_dump", "credentials", "stealer_logs",
    "iab_corporate",
    "crimeware_tooling", "crime_aas", "telecom_abuse",
    "phishing_delivery", "fraud_ops", "infra_resale",
    "recruiting", "alliance", "crew_ops",
]
assert len(LABELS) == 16, "taxonomy drift: expected 16 leaf labels"


def label_vec(row: dict) -> list[float]:
    """Same mapping the trainer uses: list-of-names OR {name:bool} -> 16-vector."""
    lab = row.get("labels")
    if isinstance(lab, dict):
        return [1.0 if lab.get(k) else 0.0 for k in LABELS]
    if isinstance(lab, list):
        s = set(lab)
        return [1.0 if k in s else 0.0 for k in LABELS]
    return [1.0 if row.get(k) else 0.0 for k in LABELS]


def _build_anonymizer():
    """One multi-language Presidio analyzer (en + es), plus the anonymizer."""
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_anonymizer import AnonymizerEngine

    cfg = {
        "nlp_engine_name": "spacy",
        "models": [
            {"lang_code": "en", "model_name": "en_core_web_sm"},
            {"lang_code": "es", "model_name": "es_core_news_sm"},
        ],
    }
    nlp = NlpEngineProvider(nlp_configuration=cfg).create_engine()
    analyzer = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en", "es"])
    anonymizer = AnonymizerEngine()

    def scrub(text: str) -> str:
        # Order matters. creds first (kill glued user/pass values before anything eats the
        # label word), then bare emails (before bd splits them), then bd.redact for the
        # opsec layer (urls/domains/handles/crypto/ip/email:pass -> fakes), then Presidio
        # en+es limited to PII_ENTITIES only. Sequential language passes avoid overlaps.
        out = scrub_sensitive(text)
        out = preserve_url_slugs(out)
        out = bd.redact(out)
        out = _PHONE.sub("<PHONE_NUMBER>", out)  # glued phones bd/presidio miss
        for lang in ("en", "es"):
            if not out.strip():
                break
            results = analyzer.analyze(text=out, language=lang, entities=PII_ENTITIES)
            if results:
                out = anonymizer.anonymize(text=out, analyzer_results=results).text
        return out

    return scrub


# Opaque raw identifiers glued into attachment filenames: content hashes, platform file-ids,
# long bare numeric runs. bd finds no domain/handle/crypto structure to fake and Presidio finds
# no PII entity, so they rode through verbatim -- yet each is a cross-dataset-correlatable
# identifier carrying ZERO model signal. Over-stripping is the safe direction for an anonymizer.
_FNAME_HEXHASH = re.compile(r"[0-9a-fA-F]{16,}")                        # md5/sha/content hashes
_FNAME_OPAQUE = re.compile(r"(?=[\w-]*[A-Za-z])(?=[\w-]*\d)[\w-]{20,}")  # mixed letter+digit file-ids
_FNAME_DIGITS = re.compile(r"\d{9,}")                                   # long bare numeric runs


def _strip_opaque_ids(stem: str) -> str:
    """Neutralize raw correlatable identifiers (hashes / platform file-ids / long digit runs)
    that no PII pass targets. Signal-free by construction, so blanket-replaced."""
    stem = _FNAME_HEXHASH.sub("x", stem)
    stem = _FNAME_DIGITS.sub("0", stem)  # before OPAQUE: collapse the run so the word survives
    stem = _FNAME_OPAQUE.sub("x", stem)
    return stem


def scrub_filename(name: str, scrub=bd.redact) -> str:
    """Scrub an attachment filename the SAME way message bodies are (the module-docstring
    contract): run the full body `scrub` over the stem -- so embedded emails/phones/@handles/
    target domains die exactly as in a body -- then strip opaque raw identifiers. Extension is
    kept (model signal). `scrub` defaults to bd.redact so standalone probes work without building
    Presidio; main() passes the full en+es pipeline. A victim-named dump
    'www.thaidairy.co.th.zip' -> faked-stem '.zip'; 'HESOYAM CLOUD.rar' survives. Campaign/tool/
    db-table names carry no victim PII and are intentionally preserved (signal)."""
    stem, dot, ext = name.rpartition(".")
    if not (dot and 1 <= len(ext) <= 5 and ext.isalnum()):
        stem, ext = name, ""
    clean = _strip_opaque_ids(scrub(stem))
    return f"{clean}.{ext}" if ext else clean


def _load_attmap() -> dict[str, dict]:
    """{redacted-text -> {kinds, files}} for corpus messages that HAVE an attachment. Keyed by
    bd.redact(text) to match the trainer's join (train_mmbert_ml._attmap), so a shared row
    carries the SAME attachment signal the model trained on. Only attachment rows are redacted,
    keeping the 160k-row scan cheap."""
    m: dict[str, dict] = {}
    if not CORPUS.exists():
        return m
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("has_attachment"):
            m[bd.redact(r["text"])] = {
                "kinds": r.get("att_kinds") or [],
                "files": r.get("att_files") or [],
            }
    return m


def selftest() -> None:
    scrub = _build_anonymizer()
    probe = (
        "HACKED BY CrewX. Target: victim.go.th (Thailand). "
        "Contact john.smith@example.com or call +1-415-555-0199. "
        "USERNAME : don88  PASSWORD : 0922655849may "
        "EMAIL: victim0823@gmail.comPASSWORD: N1ch0l45"  # glued, no space (real pattern)
    )
    got = scrub(probe)
    # PII dies
    assert "john.smith@example.com" not in got, got
    assert "555-0199" not in got, got
    assert "don88" not in got and "0922655849may" not in got, got
    assert "victim0823" not in got, got  # glued local-part
    assert "N1ch0l45" not in got, got    # glued password

    # URL-only forum-thread row: slug words must survive bd faking the host
    urlrow = "https://breached.st/threads/database-icpo-interpol-int.86546/"
    g2 = scrub(urlrow)
    assert "database" in g2 and "interpol" in g2, g2  # signal preserved
    assert "breached.st" not in g2, g2                # host faked

    # Combo/stealer-log victim record: email:pass glue + labeled PII fields (row 508 shape)
    combo = ("randy@cctv.act.edu.au:Tiger358 | Full Name: Thomas Brady | "
             "Phone: +61412345678, +61498765432 | Address: 25 Koala Rd, Mona Vale, NSW, 2103")
    g3 = scrub(combo)
    for leak in ("Tiger358", "Thomas Brady", "randy@cctv", "+61412345678", "Koala Rd"):
        assert leak not in g3, (leak, g3)
    assert "Full Name" in g3 and "Phone" in g3, g3  # field structure kept

    # Stealer-log triples: domain:user:pass and phone:pass lines (rows 640/693/923 shape)
    logs = (
        "https://acc.kel.go.id/auth/login:0812345:naval99\n"
        "web.face.com:iva.voss@gmail.com:sanchez01\n"
        "081234567:Blkkppnh22!\n"
        "dj.pa.go.id:82551:leoputra01"
    )
    g4 = scrub(logs)
    for leak in ("naval99", "sanchez01", "Blkkppnh22!", "leoputra01", "iva.voss@gmail.com"):
        assert leak not in g4, (leak, g4)
    # prose with a colon must NOT be redacted
    assert scrub("Note: the database was leaked here") == "Note: the database was leaked here"
    assert scrub("End Time: 14:30 duration 02:15") == "End Time: 14:30 duration 02:15"

    # space-separated bare user:pass block (row 655 shape) + email:pass mix
    block = "jun88:Da45xx14 kambar:jono99 alex@gmail.com:Elite!$ urial:Ur7pass"
    g5 = scrub(block)
    for leak in ("Da45xx14", "jono99", "Elite!$", "Ur7pass", "kambar", "jun88", "urial"):
        assert leak not in g5, (leak, g5)

    # Indonesian CRM leads (row 902 shape): honorific name + Jalan street
    crm = "leadA::Jl. Sudirman Kav. 52::Bpk. Abi Santoso::phone"
    g6 = scrub(crm)
    assert "Sudirman" not in g6 and "Abi Santoso" not in g6, g6

    # Breach template with dash-separated labels (rows 698/862 shape): PW/PWD must die,
    # URL line must survive (target = signal)
    tmpl = "URL - https://www.cas.chula.ac.th/cas/\nUSR - 6012345\nPW  - goldfish00\nPWD - Sp3cial!"
    g7 = scrub(tmpl)
    for leak in ("goldfish00", "Sp3cial!", "6012345"):
        assert leak not in g7, (leak, g7)
    assert "URL -" in g7 and "cas" in g7, g7  # target/signal survives
    # scene-vocab signal survives (no over-tagging)
    assert "HACKED BY" in got, got
    assert "Thailand" in got, got  # LOCATION not tagged
    assert "USERNAME" in got and "PASSWORD" in got, got  # cred-dump structure kept

    # attachment filenames: extension (signal) kept, target domain stripped, clean name survives
    assert scrub_filename("HESOYAM CLOUD.rar") == "HESOYAM CLOUD.rar", scrub_filename("HESOYAM CLOUD.rar")
    vic = scrub_filename("www.thaidairy.co.th.zip")
    assert "thaidairy" not in vic and vic.endswith(".zip"), vic
    # opaque raw identifiers die: content hash, platform file-id, long digit run
    assert scrub_filename("cb1382b38dee7fa54df7314824103e92_1.mp4") == "x_1.mp4", \
        scrub_filename("cb1382b38dee7fa54df7314824103e92_1.mp4")
    assert scrub_filename("o8nIEm0PiiAT0fJgERiBUD7TRAKbUyo6HBXfBi.mp4") == "x.mp4", \
        scrub_filename("o8nIEm0PiiAT0fJgERiBUD7TRAKbUyo6HBXfBi.mp4")
    assert scrub_filename("backup_20260717093045.sql") == "backup_0.sql", \
        scrub_filename("backup_20260717093045.sql")
    # campaign/tool name carries no victim PII -> intentionally preserved (signal)
    assert scrub_filename("PegasusCloud.rar") == "PegasusCloud.rar", scrub_filename("PegasusCloud.rar")
    print("selftest OK ->", got)


def main() -> None:
    scrub = _build_anonymizer()
    attmap = _load_attmap()  # redacted-text -> {kinds, files} for messages with an attachment
    fname_cache: dict[str, str] = {}  # dedup: log-cloud bots repost the same filename thousands of times
    rows = [json.loads(l) for l in SRC.read_text(encoding="utf-8").splitlines() if l.strip()]
    written = with_att = 0
    with OUT.open("w", encoding="utf-8") as f:
        for i, r in enumerate(rows, 1):
            override = _ROW_OVERRIDES.get(hashlib.sha1(r["text"].encode()).hexdigest())
            rec = {
                "text": override if override is not None else scrub(r["text"]),
                "labels": label_vec(r),
                "tier": r.get("tier"),
            }
            # attachment signal: same join the model uses (bd.redact-keyed), filenames scrubbed
            att = attmap.get(bd.redact(r["text"]))
            rec["has_attachment"] = att is not None
            if att:
                with_att += 1
                rec["att_kinds"] = att["kinds"]
                rec["att_files"] = [
                    fname_cache.setdefault(fn, scrub_filename(fn, scrub)) for fn in att["files"]
                ]
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1
            if i % 100 == 0:
                print(f"  {i}/{len(rows)}", file=sys.stderr)
    print(f"wrote {written} rows ({with_att} with attachments) -> {OUT}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
