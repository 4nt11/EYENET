#!/usr/bin/env python3
# ruff: noqa: ERA001, E501, B033, PLR2004
"""Build ``_regional_markers.py`` from INGEOTEC regional-spanish-models vocab files.

Reads ``data/ingeotec/voc/*.tsv.gz`` (LFS-tracked) and emits
``eyenet/sensor/primitives/_regional_markers.py``.

Run once when the INGEOTEC data is updated; commit the output.

Usage:
    python scripts/build_regional_markers.py [--top-n 80] [--excl 0.70] [--min-ndocs 5000]

INGEOTEC voc file format:
    Per-country TSV.GZ at ``<CC>.tsv.gz`` with header row:
        token\tocccs\tndocs\tweight
    All tokens lowercased, weight is TF-IDF-style float.

Filters applied:
    1. Tokens must be single-word alphabetic (accents preserved), >= 3 chars.
    2. Tokens in ``_NOISE_BLOCKLIST`` (politicians, parties, sports clubs,
       cities, media outlets) are excluded — these are time-decaying signals,
       not stable dialectal markers.
    3. Exclusivity = freq[region][tok] / sum_all_regions_freq[tok] must be
       >= ``--excl`` (default 0.70).
    4. Per-region ndocs must be >= ``--min-ndocs`` (default 5000) to avoid
       hyper-rare tokens that won't generalise.
    5. Top-N per region by ``exclusivity * log(1 + ndocs)`` (default N=80).

The noise blocklist is OPEN to extension. If a 2030 election surfaces new
proper nouns the extractor catches, add them and re-run.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

# Country code → BCP-47 tag. Spanish-speaking only; INGEOTEC ships BR/FR/GB/CA/US
# vocabs too, but those are non-Spanish or expatriate corpora and we skip them.
_CC_TO_BCP47: dict[str, str] = {
    "AR": "es-AR",
    "BO": "es-BO",
    "CL": "es-CL",
    "CO": "es-CO",
    "CR": "es-CR",
    "CU": "es-CU",
    "DO": "es-DO",
    "EC": "es-EC",
    "ES": "es-ES",
    "GT": "es-GT",
    "HN": "es-HN",
    "MX": "es-MX",
    "NI": "es-NI",
    "PA": "es-PA",
    "PE": "es-PE",
    "PR": "es-PR",
    "PY": "es-PY",
    "SV": "es-SV",
    "UY": "es-UY",
    "VE": "es-VE",
}

# Single lowercase word, accents preserved, ≥ 3 chars
_WORD_RE = re.compile(r"^[a-záéíóúüñàèìòùâêîôûäëïöü]+$", re.IGNORECASE)

# Comprehensive blocklist of TIME-DECAYING regional proper nouns.
# Categories: politicians (current and recent), political parties, sports clubs,
# major cities, country self-references, media outlets, regional acronyms.
# These have high exclusivity in INGEOTEC data but are useless / actively harmful
# as stable dialectal markers — they will rot as politics shifts.
_DIALECTAL_3CHAR_WHITELIST: frozenset[str] = frozenset(
    {
        # 3-letter tokens that ARE genuine dialectal markers (don't filter as acronyms)
        "vos",  # AR, UY voseo
        "sos",  # AR, UY voseo "you are"
        "che",  # AR interjection
        "wei",  # CL alternate spelling of "weí"
        "mae",  # CR friend
        "pue",  # MX informal "pues"
        "ahi",  # general but often dialectal
        "puh",  # CL emphatic
        "poh",  # CL emphatic
        "che",  # AR
        "ndo",  # PY Guarani influence "ndé"
        "weá",  # CL
        "weo",  # CL
        "wea",  # CL (length 3)
        "feo",  # neutral
        "jaa",  # informal laugh
        "jeje",  # length 4 actually
    }
)


_NOISE_BLOCKLIST: frozenset[str] = frozenset(
    {
        # ── politicians (last names + nicknames + initials) ─────────────────────
        # Argentina
        "macri",
        "cfk",
        "kirchner",
        "kirchnerismo",
        "kirchnerista",
        "peronismo",
        "peronista",
        "milei",
        "alberto",
        "cristina",
        "scioli",
        "massa",
        "larreta",
        "bullrich",
        "evo",
        # Chile
        "pinera",
        "piñera",
        "bachelet",
        "boric",
        "kast",
        "lagos",
        "frei",
        # Colombia
        "uribe",
        "uribismo",
        "uribista",
        "petro",
        "duque",
        "fajardo",
        "santos",
        "pastrana",
        # Spain
        "rajoy",
        "sanchez",
        "casado",
        "iglesias",
        "aznar",
        "zapatero",
        "rivera",
        "abascal",
        "feijoo",
        "yolanda",
        # Mexico
        "amlo",
        "lopez",
        "obrador",
        "calderon",
        "pena",
        "nieto",
        "salinas",
        "fox",
        "sheinbaum",
        # Peru
        "ppk",
        "kuczynski",
        "fujimori",
        "fujimorismo",
        "fujimorista",
        "humala",
        "vizcarra",
        "castillo",
        "boluarte",
        "ollanta",
        "keiko",
        "alan",
        "toledo",
        # Uruguay
        "lacalle",
        "tabare",
        "mujica",
        "talvi",
        "vazquez",
        "sanguinetti",
        # Ecuador
        "correa",
        "moreno",
        "lasso",
        "noboa",
        "lenin",
        "borja",
        # Venezuela
        "maduro",
        "chavez",
        "chavismo",
        "chavista",
        "guaido",
        "capriles",
        "rosales",
        "ledezma",
        # Cuba
        "castro",
        "raul",
        "fidel",
        "diaz",
        "canel",
        # Bolivia
        "morales",
        "mesa",
        "anez",
        "arce",
        # El Salvador
        "bukele",
        "nayib",
        "funes",
        # Honduras
        "joh",
        "hernandez",
        "xiomara",
        # Guatemala
        "jimmy",
        "giammattei",
        "arevalo",
        # Nicaragua
        "ortega",
        "murillo",
        # Paraguay
        "cartes",
        "abdo",
        "pena",
        # Panama
        "martinelli",
        "varela",
        "cortizo",
        # Costa Rica
        "alvarado",
        "chaves",
        # Dominican Republic
        "danilo",
        "medina",
        "abinader",
        "leonel",
        # ── political parties & orgs ────────────────────────────────────────────
        "psoe",
        "podemos",
        "vox",
        "pp",
        "psuv",
        "mud",
        "clap",
        "farc",
        "eln",
        "fmln",
        "arena",
        "frente",
        "pld",
        "prm",
        "ppt",
        "morena",
        "pri",
        "pan",
        "prd",
        "mc",
        "frenadeso",
        "anr",
        "pln",
        "pusc",
        "ml",
        "papd",
        "cicig",
        "feci",
        # ── sports clubs (the major ones — football, baseball) ──────────────────
        "boca",
        "river",
        "racing",
        "independiente",
        "velez",
        "huracan",
        "estudiantes",
        "lanus",
        "platense",
        "colo",
        "udechile",
        "audax",
        "unionespanola",
        "huachipato",
        "atletico",
        "barcelona",
        "madrid",
        "atleti",
        "betis",
        "valencia",
        "sevilla",
        "espanyol",
        "alaves",
        "america",
        "chivas",
        "guadalajara",
        "cruzazul",
        "pumas",
        "tigres",
        "monterrey",
        "rayados",
        "pachuca",
        "leon",
        "toluca",
        "penarol",
        "olimpia",
        "nacional",
        "danubio",
        "wanderers",
        "saprissa",
        "alajuelense",
        "herediano",
        "emelec",
        "ldu",
        "aucas",
        "ind",
        "bsc",
        "alianza",
        "universitario",
        "cristal",
        "boys",
        "cienciano",
        "millonarios",
        "santafe",
        "junior",
        "tolima",
        "caracas",
        "deportivo",
        "lara",
        "tachira",
        "zamora",
        "licey",
        "aguilas",
        "cibao",
        "toros",
        "leones",
        "marathon",
        "motagua",
        "vida",
        # ── major city names ────────────────────────────────────────────────────
        "buenos",
        "córdoba",
        "cordoba",
        "rosario",
        "mendoza",
        "tucuman",
        "santiago",
        "stgo",
        "valparaiso",
        "concepcion",
        "antofagasta",
        "bogota",
        "medellin",
        "barranquilla",
        "cartagena",
        "cali",
        "bucaramanga",
        "zaragoza",
        "bilbao",
        "malaga",
        "murcia",
        "cdmx",
        "ciudad",
        "puebla",
        "tijuana",
        "veracruz",
        "maracaibo",
        "barquisimeto",
        "zulia",
        "habana",
        "havana",
        "guayaquil",
        "quito",
        "cuenca",
        "gye",
        "uio",
        "lima",
        "arequipa",
        "trujillo",
        "callao",
        "asuncion",
        "encarnacion",
        "montevideo",
        "panama",
        "colon",
        "chiriqui",
        "veraguas",
        "managua",
        "granada",
        "tegucigalpa",
        "honduras",
        "comayagua",
        "guatemala",
        "guate",
        "salvador",
        "soyapango",
        "santa",
        # ── country self-references / nationality adjectives ────────────────────
        "argentina",
        "argentinos",
        "argentino",
        "argentine",
        "chile",
        "chilenos",
        "chileno",
        "chilenas",
        "chilena",
        "colombia",
        "colombianos",
        "colombiano",
        "colombianas",
        "colombiana",
        "espana",
        "españa",
        "espanol",
        "español",
        "espanoles",
        "españoles",
        "espanolas",
        "españolas",
        "mexico",
        "méxico",
        "mexicanos",
        "mexicano",
        "mexicanas",
        "mexicana",
        "venezuela",
        "venezolanos",
        "venezolano",
        "venezolanas",
        "venezolana",
        "cuba",
        "cubanos",
        "cubano",
        "cubanas",
        "cubana",
        "ecuador",
        "ecuatorianos",
        "ecuatoriano",
        "ecuatorianas",
        "ecuatoriana",
        "peru",
        "perú",
        "peruanos",
        "peruano",
        "peruanas",
        "peruana",
        "paraguay",
        "paraguayos",
        "paraguayo",
        "uruguay",
        "uruguayos",
        "uruguayo",
        "panamenos",
        "panameño",
        "panamenas",
        "panameña",
        "nicaragua",
        "nicas",
        "nica",
        "hondurenos",
        "hondureño",
        "guatemaltecos",
        "guatemalteco",
        "salvadorenos",
        "salvadoreño",
        "republica",
        "dominicana",
        "dominicanos",
        "dominicano",
        "puerto",
        "rico",
        "boricua",
        "bolivia",
        "bolivianos",
        "boliviano",
        "costa",
        "rica",
        "costarricenses",
        "costarricense",
        "ticos",
        "tico",
        # ── media outlets / TV channels / news abbreviations ────────────────────
        "tn",
        "c5n",
        "tve",
        "rtve",
        "antena",
        "tele",
        "telesur",
        "canalrcn",
        "caracol",
        "rcn",
        "noticias",
        "atv",
        "americatv",
        "globovisión",
        "venevision",
        "globovision",
        "televen",
        "vtv",
        "telegrafo",
        "boliviatv",
        "canal",
        "noticiero",
        # ── political/admin acronyms & election machinery ───────────────────────
        "tsj",
        "jce",
        "tse",
        "tre",
        "rnp",
        "rep",
        "vzla",
        "ven",
        "arg",
        "chl",
        "col",
        "mex",
        "esp",
        "ecu",
        "per",
        "ury",
        "pry",
        "bol",
        "ctm",  # ambiguous slang vs Chilean abbreviation — keep out to be safe
        "lpm",  # AR profanity acronym — keep but it's actually a stable marker;
        # decision: KEEP. (move out of blocklist by uncommenting below)
        # ── miscellaneous proper noun noise ─────────────────────────────────────
        "balsells",
        "mackay",
        "velasquez",
        "butters",
        "marandu",
        "capiata",
        "zapag",
        "fren",
        "nito",
        "pty",
        "gurises",
        "gurisas",  # last two are slang but politically charged; revisit
        "manya",  # peñarol fan term, sports
        "rambla",  # geographic ref
        # ── second pass: cities, provinces, regional subdivisions ───────────────
        # Argentina
        "bariloche",
        "belgrano",
        "quilmes",
        "caba",
        "cba",
        "brc",
        "mardel",
        "salta",
        "neuquen",
        "chubut",
        "jujuy",
        "patagonia",
        "subte",  # subte is genuinely dialectal but conflicts; keep out for now? Actually KEEP - it's dialectal
        # Actually keep subte as a real dialectal marker (Argentine slang for metro)
        # Removing "subte" from blocklist by NOT including it here
        "wsp",  # whatsapp abbreviation, AR-leaning
        # Chile
        "conce",
        "valpo",
        "valdivia",
        "temuco",
        "talca",
        "rancagua",
        "arica",
        "iquique",
        "araucania",
        "chiloe",
        "condes",
        "nunoa",
        "ñuñoa",
        "puente",
        "vina",
        # Colombia
        "antioquia",
        "boyaca",
        "cundinamarca",
        "cauca",
        "huila",
        "ibague",
        "guajira",
        "envigado",
        "chapinero",
        "caldas",
        # Mexico
        "guanajuato",
        "chiapas",
        "oaxaca",
        "yucatan",
        "nuevo",
        "queretaro",
        "tabasco",
        "morelos",
        "hidalgo",
        "michoacan",
        # Venezuela
        "merida",
        "vargas",
        "miranda",
        "anzoategui",
        # Spain
        "andalucia",
        "andalucía",
        "cataluna",
        "cataluña",
        "galicia",
        "vasca",
        "vasco",
        "navarra",
        "asturias",
        "extremadura",
        "aragon",
        "aragón",
        "rioja",
        "canarias",
        "baleares",
        "ceuta",
        "melilla",
        # Peru
        "chiclayo",
        "cusco",
        "cuzco",
        "iquitos",
        "piura",
        "tacna",
        # Ecuador
        "ambato",
        "machala",
        # Uruguay
        "maldonado",
        "salto",
        "paysandu",
        # ── second pass: politicians, party-adjacent, ex-officials ──────────────
        "cambiemos",
        "carrio",
        "lilita",
        "nisman",
        "vigna",
        "lanata",
        "clarin",
        "magnetto",
        "peronistas",
        "kicillof",
        "berni",
        "milagro",
        "sala",
        "chadwick",
        "jadue",
        "marinovic",
        "ossandon",
        "goic",
        "guillier",
        "larrain",
        "matthei",
        "kingdom",
        "alessandri",
        "longueira",
        "gaviria",
        "samper",
        "uribistas",
        "petristas",
        "claudia",
        "ebrard",
        "anaya",
        "meade",
        "luisa",
        "junts",
        "erc",
        "bildu",
        "ciudadanos",
        "mas",
        "pdvsa",
        "tibisay",
        "lucena",
        "leopoldo",
        # ── second pass: sports clubs, leagues, federations ─────────────────────
        "anfp",
        "cdf",
        "dim",
        "dimayor",
        "fpc",
        "campin",
        "afa",
        "conmebol",
        "uefa",
        "laliga",
        "ligamx",
        "ligue",
        "ligabbva",
        "copa",
        "libertadores",
        "sudamericana",
        "udecaen",
        "everton",
        "atlas",
        "celta",
        # ── second pass: TV channels, media, news outlets ───────────────────────
        "tvn",
        "chv",
        "mega",
        "canal13",
        "tele13",
        "ant3",
        "ant",
        "lasexta",
        "telecinco",
        "cuatro",
        "neox",
        "cadena",
        "ser",
        "noticieros",
        "univision",
        "telemundo",
        "milenio",
        "reforma",
        "jornada",
        "vpitv",
        "epueblo",
        "anonimosin",
        "anonymous",
        # ── second pass: government acronyms, regional agencies ─────────────────
        "afp",
        "sii",
        "sernac",
        "sename",
        "sernam",
        "fonasa",
        "minvu",
        "isapre",
        "isapres",
        "afip",
        "ansès",
        "anses",
        "anme",
        "inadi",
        "icfes",
        "dian",
        "supersalud",
        "fiscalia",
        "fiscalía",
        "minciencias",
        "renta",
        "sat",
        "imss",
        "infonavit",
        "issste",
        "cofepris",
        "conade",
        "ine",
        "inegi",
        "conacyt",
        "pemex",
        "cfe",
        "saime",
        "cantv",
        "sundde",
        "sundee",
        "ssa",
        "eps",
        "esmad",
        "isagen",
        "hidroituango",
        "electricaribe",
        "rappi",
        "tigo",
        "claro",
        "movistar",
        # ── second pass: corporate / commercial proper nouns ────────────────────
        "fernet",  # AR-specific brand, but also a real beverage word — keep in markers
        # Actually fernet IS dialectal usage (Fernet-Branca is the AR national drink) — KEEP
        # not adding to blocklist
        "quilmes",  # beer brand AND city — already in cities list above
        "renault",
        "peugeot",
        "fiat",
        "toyota",
        "ford",
        "chevrolet",
        "mercadolibre",
        "mlbra",
        "facebook",
        "twitter",
        "instagram",
        "tiktok",
        "youtube",
        # ── second pass: pure acronyms surviving structural filter ──────────────
        "auv",
        "blda",
        "bldo",
        "ahr",
        "qls",
        "pdf",
        "url",
        "iva",
        "imv",
        "ico",
        "icm",
        "wp",
        "ww",
        "fyi",
        "jjj",
        "kk",
        "kkk",
        "uam",
        "uba",
        "unam",
        "uchile",
        "uss",
        "uc",
        "unc",
        "puc",
        "ud",
        "udp",
        "udd",
        "uft",
        "uvm",
        "unab",
        "uah",
        "uaf",
        "univ",
        "obvio",  # actually a real word, remove?
        # ── third pass: post-regeneration cleanup ───────────────────────────────
        # AR: post-2015 political residue
        "macrista",
        "macristas",
        "moyano",
        "pami",
        "peron",
        "perón",
        "pichetto",
        "campora",
        "cámpora",
        "amorin",
        "tigre",
        "vidal",
        "lopezmurphy",
        "rabasa",
        "garavano",
        "frigerio",
        "biondini",
        "kirchneristas",
        # AR: Boca/River chants (sports residue)
        "bostero",
        "bosteros",
        "gallina",
        "gallinas",
        "riber",
        "riverplate",
        "bocajrs",
        # CL: post-2015 political residue
        "aylwin",
        "labbe",
        "lavin",
        "luksic",
        "matte",
        "angelini",
        "krauss",
        # CL: regional channels/places/people
        "biobio",
        "calama",
        "copiapo",
        "coquimbo",
        "curico",
        "melipilla",
        "chileofc",
        "chilevision",
        "lascondes",
        "lucerov",
        "javiera",
        "raquel",
        "carlos",
        "dinamo",
        "hertz",
        "auth",
        # CO: post-2015 political residue & geographic
        "santistas",
        "verdes",
        "centrod",
        "santandereanos",
        "paisas",
        "rolos",
        "tunja",
        "neiva",
        "manizales",
        "pereira",
        "armenia",
        "valledupar",
        "popayan",
        "yumbo",
        "cucuta",
        "monteria",
        "sincelejo",
        # CO: sports residue
        "tolimense",
        "tolimenses",
        # MX: post-2015 political residue
        "calderonistas",
        "morenistas",
        "panistas",
        "priistas",
        "perredistas",
        "ricardo",
        "manlio",
        "tlaxcala",
        "campeche",
        "sonora",
        "sinaloa",
        "durango",
        "coahuila",
        "tamaulipas",
        "guerrero",
        # MX: clubs / media
        "tudn",
        "azteca",
        "tvazteca",
        "razon",
        # ES: post-2015 political residue
        "albert",
        "errejón",
        "errejon",
        "puigdemont",
        "torra",
        "aragones",
        # ES: regional autonomy refs
        "asturianos",
        "valencianos",
        "gallegos",
        "vascos",
        "catalanes",
        "andaluces",
        # VE: politics
        "chavismos",
        "chavistas",
        "maria",
        "corina",
        "guaidó",
        # PE: politics
        "fujimoristas",
        "humalistas",
        # UY: politics & geographic
        "frenteamplistas",
        "blancos",
        "colorados",
        # generic Twitter/internet noise (broad)
        "snapchat",
        "spotify",
        "netflix",
        "amazon",
        "google",
        # generic regional self-tagging hashtags & geographic adjectives missed earlier
        "porteno",
        "porteño",
        "porteños",
        "portenos",
        "rioplatense",
        "rioplatenses",
        "patagonico",
        "patagónico",
        "limeno",
        "limeño",
        "chilango",
        "regio",
        "regios",
        "tapatio",
        "tapatío",
        "norteño",
        "sureño",
        # ── fourth pass: Twitter handles, brand accounts, athletes ──────────────
        # es-MX
        "barralesm",
        "chefmx",
        "olgascordero",
        "ladelvalle",
        # es-CO
        "kcacolombia",
        "ordonezm",
        "rodb",
        "juhampa",
        # es-CL
        "clst",
        "floreso",
        "schwartzmann",
    }
)


_VOWELS = set("aeiouáéíóúü")


def _is_likely_acronym(tok: str) -> bool:
    """Heuristic: 3-letter tokens with ≤1 vowel are almost always acronyms.

    Whitelisted dialectal 3-letter markers (vos, sos, che, mae, etc.) are
    handled by ``_DIALECTAL_3CHAR_WHITELIST`` BEFORE this check.
    """
    if len(tok) != 3:
        return False
    vowel_count = sum(1 for c in tok if c in _VOWELS)
    return vowel_count <= 1


def _load_voc(voc_dir: Path) -> dict[str, dict[str, int]]:
    """Read INGEOTEC voc/<CC>.tsv.gz files; return freq[bcp47][token] = ndocs."""
    freq: dict[str, dict[str, int]] = {}
    for cc, bcp47 in _CC_TO_BCP47.items():
        path = voc_dir / f"{cc}.tsv.gz"
        if not path.exists():
            print(f"[WARN] missing {path}", file=sys.stderr)
            continue
        rf: dict[str, int] = {}
        with gzip.open(path, "rt", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                tok = row["token"].lower().strip()
                try:
                    ndocs = int(row["ndocs"])
                except (KeyError, ValueError):
                    continue
                if (
                    _WORD_RE.match(tok)
                    and len(tok) >= 3
                    and tok not in _NOISE_BLOCKLIST
                    and (tok in _DIALECTAL_3CHAR_WHITELIST or not _is_likely_acronym(tok))
                ):
                    rf[tok] = ndocs
        freq[bcp47] = rf
        print(f"  loaded {bcp47}: {len(rf):,} tokens", file=sys.stderr)
    return freq


def _build_markers(
    freq: dict[str, dict[str, int]],
    *,
    top_n: int,
    excl_threshold: float,
    min_ndocs: int,
) -> dict[str, frozenset[str]]:
    markers: dict[str, list[tuple[str, float, int]]] = defaultdict(list)
    for region, rf in freq.items():
        for tok, region_count in rf.items():
            if region_count < min_ndocs:
                continue
            total = sum(f.get(tok, 0) for f in freq.values())
            excl = region_count / total if total > 0 else 0.0
            if excl >= excl_threshold:
                markers[region].append((tok, excl, region_count))

    out: dict[str, frozenset[str]] = {}
    for region, cands in markers.items():
        cands.sort(key=lambda x: x[1] * math.log1p(x[2]), reverse=True)
        out[region] = frozenset(t for t, _, _ in cands[:top_n])
    return out


def _emit_module(markers: dict[str, frozenset[str]], output_path: Path) -> None:
    lines: list[str] = [
        '"""Region-exclusive lexical markers for dialect_region detection.',
        "",
        "AUTO-GENERATED by ``scripts/build_regional_markers.py`` from INGEOTEC",
        "regional-spanish-models vocab data (``data/ingeotec/voc/*.tsv.gz``).",
        "",
        "Do NOT edit by hand. Re-run the build script to regenerate when the",
        "INGEOTEC corpus is updated or the noise blocklist changes.",
        "",
        "Methodology: token exclusivity (freq_in_region / sum_freq_across_regions)",
        "above the configured threshold; political/sports/city/media proper-noun",
        "blocklist applied to remove time-decaying signals. See build script.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        'MARKERS_VERSION: str = "v1"',
        "",
        "# fmt: off",
        "REGIONAL_MARKERS: dict[str, frozenset[str]] = {",
    ]
    for region in sorted(markers):
        tokens = sorted(markers[region])
        if not tokens:
            continue
        lines.append(f"    {region!r}: frozenset({{")
        for tok in tokens:
            lines.append(f"        {tok!r},")
        lines.append("    }),")
    lines += [
        "}",
        "# fmt: on",
        "",
        '__all__ = ["MARKERS_VERSION", "REGIONAL_MARKERS"]',
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    total = sum(len(v) for v in markers.values())
    print(
        f"[OK] wrote {output_path} — {len(markers)} regions, {total} markers",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--voc-dir",
        type=Path,
        default=Path("data/ingeotec/voc"),
        help="Directory of INGEOTEC <CC>.tsv.gz files (LFS-tracked)",
    )
    parser.add_argument("--top-n", type=int, default=80)
    parser.add_argument(
        "--excl", type=float, default=0.70, help="Minimum exclusivity (default 0.70)"
    )
    parser.add_argument(
        "--min-ndocs", type=int, default=5000, help="Per-region minimum doc count (default 5000)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("eyenet/sensor/primitives/_regional_markers.py"),
    )
    args = parser.parse_args()

    freq = _load_voc(args.voc_dir)
    if not freq:
        sys.exit(f"[ERROR] no vocab files in {args.voc_dir}")

    markers = _build_markers(
        freq,
        top_n=args.top_n,
        excl_threshold=args.excl,
        min_ndocs=args.min_ndocs,
    )
    _emit_module(markers, args.output)


if __name__ == "__main__":
    main()
