# Per-victim stealer-family classification

## Problem

Victims land in the artifact drawer with no attribution to a stealer family.
The drawer shows country, credential counts, wallet presence, MITRE
techniques, but never "this is a Lumma log" / "this is stealc". Operators
read file layouts by eye to guess the family. That does not scale, does not
survive catalog growth, and drops on the floor every day of corpus intake.

The pieces are present, un-stitched:

- `eyenet/stealer/families/*.yaml` is a 30+ entry catalog. Entries declare
  `slug`, `name`, `signature_files`, `loaders`, `distribution_channels`,
  `references`. Good metadata.
- Stealer families (lumma, vidar, stealc, meta, rhadamanthys, mystic, opus,
  acr, aware_crypter, gabb_grabber) are commingled in the same catalog with
  content families (cookies, browser_passwords, firefox_logins,
  google_oauth_tokens, discord_tokens) and tools (anydesk, filezilla,
  telegram_desktop). No `kind:` discriminator separates them.
- Gotractor rules carry a `family:` field, but that is the *content* family
  (cookies, victim_cookies, browser_passwords), not the *stealer* family
  (lumma, vidar). An extracted-record's `family` is "which rule produced
  me", not "which stealer dropped this victim".
- Nothing scores a victim against the catalog.

We also mis-serve the catalog: we display content and tool entries in a UI
that implies "pick a family for this record" where the right pick is
usually a content family (cookies) rather than a stealer family (lumma),
when both are equally valid in different senses.

## Target end state

Every victim carries a verdict:

```
{
  "slug": "stealc",
  "kind": "stealer",
  "confidence": 0.84,
  "evidence": [
    "sig_file:stealer_info.yaml",
    "sig_rule:stealer_info_yaml",
    "sig_path:Browser/Cookies/",
    "build_tag:^mix$"
  ],
  "runners_up": [
    ["lumma", 0.42],
    ["vidar", 0.18]
  ]
}
```

That verdict drives:

- A **SUSPECTED FAMILY** tile in the drawer header, with a click-open
  evidence popover.
- A family filter on the artifacts list.
- A `/stealer/families/{slug}` landing page listing every victim attributed
  to that family with aggregate telemetry.
- A ground-truth override loop: operator says "no, this is vidar"; the
  override feeds a tuning dashboard that scores the classifier.

## Schema (the family YAML)

A family declares what *being* that family looks like. Current fields
stay. New fields:

```yaml
slug: stealc
name: Stealc
kind: stealer                         # NEW. stealer | content | tool |
                                      # combolist | leak_pack. Only
                                      # kind=stealer is a classifier target.
status: active
first_seen_year: 2023
aliases: [Stealc]

# Positive signals. Any match contributes weighted to the score.
signature_files:                      # existing
  - System.txt
  - Passwords.txt
  - InstalledSoftware.txt
signature_paths:                      # NEW. Path prefix / substring patterns
  - Browser/Cookies/                  # presence of this layout = signal
  - Autofills/
signature_rule_ids:                   # NEW. gotractor rule_ids that fire
  - stealer_info_yaml                 # for this family, by observation
  - passwords_block_divider
  - environment_windows
build_tag_regex: "^(mix|stealc_.*)$"  # NEW. Regex match against the
                                      # build_tag canonical field. When
                                      # present + matches, this is the
                                      # strongest single signal (op-wise
                                      # it is near ground-truth).

# Negative signals. Presence REDUCES this family's score. Kills false
# positives. The common case is two stealers sharing most layout.
antisignature_files:                  # NEW
  - GoogleTokens.txt                  # if this is here it is likely lumma
antisignature_rule_ids: []            # NEW

# Scoring controls. Defaults live in classifier.py; override when the
# family needs non-default tuning.
confidence_floor: 0.35                # NEW. Below this, do not claim this
                                      # victim. Avoids 1-file matches
                                      # driving a verdict.
signal_weights:                       # NEW. Optional per-family override
  sig_file: 1.0
  sig_path: 1.5
  sig_rule: 2.0
  build_tag: 5.0
  anti_file: -2.0
  anti_rule: -2.5
```

Content and tool families get only `kind:` added and nothing else; they are
not classifier targets, their signal fields stay empty. Catalog growth is
non-invasive.

## Classifier

Signal-based weighted scoring, not a Jaccard. Per family:

```
for signal in family.signals:
    if signal matched by victim evidence set:
        score += weight(signal)
    else:
        if signal is "required":
            score = 0   # knockout
```

Victim evidence set is computed once per classify call:

- `files`: distinct `filename` from `file_audit` for `(archive, victim)`,
  non-empty / non-binary.
- `paths`: distinct relative path prefixes (first + second path segment).
- `rule_ids`: distinct `rule_id` from `extracted_records` for the same
  (archive, victim).
- `build_tag`: the value of canonical `build.version` (derived from any
  record whose fields carry it; typically `stealer_info_yaml`).

A signal is `matched` iff its pattern matches at least one element of the
corresponding evidence set (substring for paths, literal for files and
rule_ids, regex for build_tag). Weights are summed. Positive signals push
up; anti-signals push down. The final per-family score is normalized by
the sum of positive weights the family *could* have matched (i.e. by its
own max possible positive score). That keeps a catalog-rich family from
unfairly outscoring a terse one.

Ties: tiebreak by raw matched-signal count (absolute), then by catalog
first_seen_year descending (newer families are usually more specific than
older sprawling ones). Both-below-floor: no verdict, drawer shows "no
confident family" instead of a bad guess.

Verdict carries `evidence: list[str]` enumerating the signals that
contributed, so the popover can show `sig_file:Passwords.txt`,
`sig_rule:stealer_info_yaml`, `build_tag:^mix$`. Operator sees *why*.

## Storage

A new ClickHouse table and MV:

```
CREATE TABLE victim_family_verdict (
    archive_sha256 FixedString(64),
    victim_folder  String,
    slug           LowCardinality(String),
    confidence     Float32,
    evidence       Array(String),
    runners_up     Array(Tuple(String, Float32)),
    computed_at    DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(computed_at)
ORDER BY (archive_sha256, victim_folder)
```

The MV is not a straightforward join; the classifier is Python-side
(regex, weighted sum, catalog in memory). So instead of an SQL MV we
write via a side-channel worker:

- Reindex (`stealer-reindex`) classifies every victim it touches and
  writes a row into `victim_family_verdict`.
- Normal pipeline (`process_archive`) classifies at the end of the
  pipeline, once file_audit + records are populated, and writes.
- A new idempotent `stealer-reclassify` CLI sweeps the whole corpus
  without reprocessing extraction; useful after a catalog edit.

Reads: the drawer detail endpoint joins `victim_family_verdict` with
`FINAL` and returns the latest verdict. If no row exists, returns `null`
and the drawer shows "no verdict yet".

## API

Schema additions:

```
class StealerFamilyVerdict(ApiSchema):
    slug: str
    kind: str                     # stealer | content | tool | ...
    confidence: float             # 0 .. 1
    evidence: list[str]           # signal tokens
    runners_up: list[FamilyRunnerUp]   # top-N alternatives

class FamilyRunnerUp(ApiSchema):
    slug: str
    confidence: float
```

Endpoints:

- `GET /v1/stealer/artifacts/{sha}/{folder}` grows a
  `suspected_family: StealerFamilyVerdict | None` field on the detail
  envelope.
- `GET /v1/stealer/artifacts?family=<slug>` filters the list.
- `GET /v1/stealer/families/{slug}/victims` lists every victim attributed
  to `slug` (paged, same shape as /artifacts).
- `POST /v1/stealer/artifacts/{sha}/{folder}/family-override` (scope
  `write:stealer`) stores an operator verdict override. Feeds the
  tuning dashboard.
- `GET /v1/stealer/families/metrics` computes per-family P/R against
  override ground-truth; dashboard tile.

## Frontend

- **Drawer tile** `SUSPECTED FAMILY`. Shows slug + confidence bar.
  Click-opens an evidence popover (list of matched signal tokens, each
  linking to the relevant file row in Files tab or record in the
  matching tab).
- **Artifacts list filter** `family: all | lumma | vidar | stealc | ...`
  dropdown populated from `kind: stealer` catalog entries.
- **Family detail page** `/stealer/families/{slug}`. Victims attributed
  (card grid same shape as /artifacts), aggregates (top countries, top
  build_tags, time distribution), rule-id coverage heatmap.
- **Tuning page classification tester**. Operator edits a family's YAML
  (signature_* fields), hits "Dry-run", sees before/after corpus shift
  in a small bar chart ("stealc was 180, would be 212; lumma 310 -> 278;
  no-verdict 90 -> 70"). Commit when happy.
- **Override UI**. "Reclassify" button on the drawer verdict tile for
  operators with `write:stealer`. Writes the override, re-renders.

## Commit ladder

The commits land in the order below. Each one is self-contained and
reviewable; each leaves the system in a shippable state. Later commits
build on earlier ones; earlier commits do not depend on later ones.

**Phase 1: Catalog discriminator (schema-only).**
- Add `kind:` to every `families/*.yaml`. Classify each existing entry
  (lumma -> stealer, cookies -> content, anydesk -> tool, combolist ->
  combolist).
- Add new optional fields to the YAML loader: `signature_paths`,
  `signature_rule_ids`, `build_tag_regex`, `antisignature_files`,
  `antisignature_rule_ids`, `confidence_floor`, `signal_weights`.
  Defaults when absent so nothing breaks.
- Loader validates `kind` is in the allowed set; loud on typos.
- No classification yet. Pure schema plumbing. Lands green.

**Phase 2: Classifier module + CLI.**
- `eyenet/stealer/classifier.py`: `classify(archive_sha, victim_folder,
  catalog, ch_client) -> FamilyVerdict | None`. Weighted-sum scorer with
  evidence list.
- Enrich the ~10 stealer-kind YAMLs with the new positive/negative
  signal fields (lumma, vidar, stealc, meta, rhadamanthys, mystic, opus,
  acr, aware_crypter, gabb_grabber). Content/tool entries stay bare.
- `eyenet/cli/main.py stealer-reclassify` CLI: sweeps the corpus,
  classifies every (archive, victim), writes to `victim_family_verdict`.
  Idempotent via ReplacingMergeTree. `--limit` / `--dry-run` /
  `--family` for tunning iteration.
- New CH table + ensure_schema wiring.
- Unit tests over fixture victims (vidar vs stealc vs lumma).

**Phase 3: Pipeline wiring.**
- `process_archive` calls `classify` at end of pipeline, writes one
  row per victim folder it touches. Also hooked into `stealer-reindex`.
- Reader method `verdict_for(archive, folder) -> FamilyVerdict | None`.

**Phase 4: API detail surface.**
- `StealerFamilyVerdict` + `FamilyRunnerUp` schemas.
- Detail endpoint returns `suspected_family: StealerFamilyVerdict |
  None` on the envelope.
- Artifacts list grows `family` query param (filters by verdict slug).

**Phase 5: FE drawer tile + list filter.**
- SUSPECTED FAMILY tile with slug + confidence.
- Evidence popover rendering the signal tokens.
- Filter dropdown on artifacts list, populated from the catalog
  (kind: stealer subset).

**Phase 6: Family detail page.**
- `/stealer/families/{slug}/victims` endpoint (paged).
- `/stealer/families/{slug}` SvelteKit route rendering card grid +
  aggregates.

**Phase 7: Operator override + ground-truth loop.**
- `POST .../family-override` endpoint (write:stealer).
- Override table (Postgres); audit-logged.
- Tuning dashboard: per-family P/R vs overrides.
- Drawer "Reclassify" button.

**Phase 8: Classification tester (tuning page).**
- Edit family YAML inline, dry-run classifier across the corpus, see
  before/after shift as a bar chart.
- No commit until explicit save.

## What is explicitly NOT in scope

- Multi-label verdicts ("this victim is both stealc and has a lumma
  plugin"). Rare in practice; the runners_up list is enough signal
  until operator data says otherwise.
- ML classifier. The weighted-signal scorer is interpretable and
  operator-tunable; adding ML is a day-two optimisation once we have a
  labeled override set and the manual classifier is the baseline.
- Cross-archive family drift ("this family evolved after 2026-01").
  Later. Current catalog is point-in-time correct.

## Open questions

1. Should the verdict table carry a pointer to the catalog version
   (sha of the YAML set) so a reclassify can skip verdicts that are
   already current? Nice-to-have, not phase-1.
2. For the override P/R dashboard, do we weight by freshness (recent
   overrides count more) or treat all overrides equal? Default to
   equal, revisit when the override corpus is large enough that
   freshness matters.
3. Family YAML schema versioning. Phase 1 should carry a `schema:
   v2` field so future deprecations are clean. Cost is one line; add
   it in Phase 1.
