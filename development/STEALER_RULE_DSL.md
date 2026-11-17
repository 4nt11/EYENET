# EYENET Stealer Rule DSL (v1)

Declarative YAML rules for classifying stealer-log victim folders and
extracting structured fields from their files. Hot-reloaded from
`/etc/eyenet/rules/stealer/*.yaml` via SIGHUP.

**Power bound:** the DSL recognizes at most context-free languages. Formal
proof: `development/stealer_rule_dsl_cfg_proof.v`.

**Trust guarantee:** the TypeScript engine in the frontend workbench
evaluates rules entirely client-side. Files loaded into the workbench
never leave the browser.

---

## 1. Rule layers

A single rule operates at exactly one of two layers:

- **L1 container**: recognizes a victim-folder shape. Signal is file
  presence patterns and folder structure. Produces family tag.
- **L3 content**: recognizes and extracts fields from a single file's
  bytes. Produces a flat dict of named fields.

(L2 "file handler routing" is implicit: the engine picks L3 rules by
matching the file's relative path against each rule's path glob.)

A rule YAML MUST set `layer: container` or `layer: content`.

---

## 2. Common envelope

```yaml
id: lumma_system_txt               # stable slug; kebab-case; unique per layer
version: 1                         # bump on breaking changes
layer: content                     # container | content
family: lumma                      # tag emitted on match
priority: 100                      # higher wins when multiple rules match
description: >
  Parses Lumma's System.txt header block.
match: { ... }                     # see section 3
extract: { ... }                   # content layer only; see section 4
map: { ... }                       # optional field renames; see section 5
normalize: [ ... ]                 # optional post-processing; see section 6
```

Fields `id`, `version`, `layer`, `family`, `match` are REQUIRED. All
others are optional.

---

## 3. `match`: the eight types

Exactly one `type:` per rule. The `match` block's shape is determined by
the type.

### 3.1 FOLDER (container layer only)

Victim-folder shape predicate. Two authoring styles:

**(a) Flat fields** (sugar for simple shapes, unchanged from v1):

```yaml
match:
  type: folder
  requires:                        # ALL must be present (relative to root)
    - System.txt
    - Autofills/
  forbids:                         # NONE may be present
    - information.txt
  optional:                        # presence boosts score but not required
    - Clipboard.txt
    - ProcessList.txt
  min_score: 2                     # count of (requires + optional) that hit
```

Evaluated as if lowered to the predicate tree:
`and(all requires, not(any forbids), at_least{k: min_score, of: requires+optional})`.

**(b) Predicate tree** (v2, use when the flat fields aren't expressive
enough, real boolean combinations, mutual exclusion, n-of-m signals):

```yaml
match:
  type: folder
  predicate:
    and:
      - path: UserInformation.txt
      - or:
          - path: worklog.txt
          - at_least:
              count: 3
              of:
                - path: Clients/DiscordTokens.txt
                - path: Clients/SteamTokens.txt
                - path: Telegram/
                - path: Extensions/
      - not: { path: pc_info.json }
```

A predicate is a dict with EXACTLY ONE key naming the operator:

| op         | arity                | semantics                                 |
|------------|----------------------|-------------------------------------------|
| `and`      | list                 | ALL children true (`and:[]` = true)       |
| `or`       | list                 | ANY child true (`or:[]` = false)          |
| `xor`      | list                 | ODD number of children true (parity)      |
| `not`      | single               | invert the child                          |
| `at_least` | `{count, of: [...]}` | at least `count` children true            |
| `exactly`  | `{count, of: [...]}` | exactly `count` children true             |
| `at_most`  | `{count, of: [...]}` | at most `count` children true             |
| `path`     | string               | literal path exists (or `/`-suffix prefix) |
| `glob`     | string               | matchGlob pattern hits any path           |

`xor` on 2 children is the usual exclusive-or; on 3+ it reduces to
odd-parity by convention (standard digital-logic semantics). Note the
`exactly: {count: 1, of: [...]}` idiom when you literally want "pick one."

Both styles can't coexist: if `predicate:` is set, the flat fields are
IGNORED with a WARN at load time. Lowering flat to tree happens
internally so the engine only ever evaluates the tree form.

Semantics: regular. Expression-tree boolean algebra over regular
predicates (literal path membership, glob matches) is closed under
boolean composition and k-of-n counting; still strictly less
expressive than CFG. Proof updated at
`development/stealer_rule_dsl_cfg_proof.v`.

### 3.2 REGEX (content layer only)

RE2 pattern, no backreferences. Named captures become extracted fields.

```yaml
match:
  type: regex
  pattern: '^HWID:\s*(?P<hwid>[A-F0-9-]+)\s*$'
  multiline: true                  # default false; ^ / $ match line bounds
  dotall: false                    # default false
extract:
  fields: [hwid]                   # which named captures to keep
```

Semantics: regular. Engine: `google-re2` (Python) / `re2-wasm` (browser).

### 3.3 DELIMITER (content layer only)

Line-oriented single-separator parse. Think CSV without quoting.

```yaml
match:
  type: delimiter
  separator: "\t"                  # any single byte string
  min_columns: 7                   # reject lines with fewer
  skip_blank: true
  skip_comment_prefix: "#"         # optional
extract:
  columns:                         # positional column index to field name
    0: host
    1: username
    6: password
```

Semantics: regular per line.

### 3.4 TEMPLATE (content layer only)

Fixed literals interleaved with named `{field}` holes. Compiled to RE2
internally (`{field}` becomes `(?P<field>.*?)` with surrounding literal
anchors).

```yaml
match:
  type: template
  template: |
    URL: {url}
    USER: {username}
    PASS: {password}
  multiline: true
extract:
  fields: [url, username, password]
```

Semantics: regular.

### 3.5 JSON (content layer only)

RFC 8259. Field extraction via JSONPath-lite (dotted + bracketed int).

```yaml
match:
  type: json
  requires_keys:                   # top-level keys that MUST exist
    - BuildID
    - HWID
extract:
  paths:
    hwid: $.HWID
    build: $.BuildID
    pm_ext_count: $.PMExtCount
    first_wallet: $.Wallets[0].address
```

Semantics: context-free.

### 3.6 YAML (content layer only)

YAML 1.2 safe_load subset (JSON-equivalent types + block maps/seqs).
Extraction mirrors JSON.

```yaml
match:
  type: yaml
  requires_keys: [Build, HWID]
extract:
  paths:
    hwid: $.HWID
    build: $.Build
```

Semantics: context-free (safe subset).

### 3.7 KEYVALUE (content layer only)

Per-line `key<sep>value`. Case-insensitive key match. Unknown keys dropped.

```yaml
match:
  type: keyvalue
  separator: ":"                   # may be multi-char, e.g. " = "
  strip_whitespace: true
  requires_keys:                   # at least these must appear
    - IP
    - HWID
extract:
  keys:                            # source key to output field
    IP: ip
    Country: country
    HWID: hwid
```

Semantics: regular.

### 3.8 KEYVALUE_INI (content layer only)

Sectioned INI. `[section]` headers scope the keys.

```yaml
match:
  type: keyvalue_ini
  requires_sections: [Hardware, Software]
extract:
  keys:
    Hardware.HWID: hwid
    Hardware.CPU: cpu
    Software.OS: os
```

Semantics: regular.

---

## 4. `extract` shape per type

Already covered inline in section 3. Summary of the field set each type
produces:

| type          | produces          |
|---------------|-------------------|
| folder        | (no fields, family tag only) |
| regex         | named captures listed in `fields` |
| delimiter     | columns mapped by index |
| template      | holes listed in `fields` |
| json / yaml   | `paths` map output |
| keyvalue      | `keys` map output |
| keyvalue_ini  | `section.key` map output |

All values are strings before `normalize` runs.

---

## 5. `map`: field renaming

Optional alias layer, applied after `extract`, before `normalize`.

```yaml
map:
  hwid: hardware_id                # rename hwid to hardware_id
  _drop: [pm_ext_count]            # delete these
```

---

## 6. `normalize`: post-processing

Ordered list of verbs. Each verb takes a field name and optional args.
All verbs are regular string-to-string transductions (CFL closure is
preserved, see proof file section 8).

```yaml
normalize:
  - { verb: strip_whitespace, field: hwid }
  - { verb: lowercase,       field: country }
  - { verb: uppercase,       field: hwid }
  - { verb: truncate,        field: user_agent, max_len: 512 }
  - { verb: int_from_string, field: pm_ext_count }
  - { verb: replace_re2,     field: os, pattern: '\s+', replacement: ' ' }
  - { verb: date_parse,      field: infected_at, format: iso8601 }
```

Verb catalog (v1):

| verb              | args                              | effect |
|-------------------|-----------------------------------|--------|
| strip_whitespace  | field                             | leading/trailing whitespace removed |
| lowercase         | field                             | ASCII-only lowercase |
| uppercase         | field                             | ASCII-only uppercase |
| truncate          | field, max_len                    | cut to max_len bytes |
| int_from_string   | field                             | parse decimal int; drop field on failure |
| replace_re2       | field, pattern, replacement       | RE2 substitution |
| date_parse        | field, format                     | iso8601 / rfc2822 / epoch_seconds |

A verb that fails (parse error, no match) DROPS the field silently.
Hard failures are a rule bug, not a parse-time runtime error.

---

## 7. Engine resolution order

Per victim folder:

1. All `layer: container` rules evaluate in parallel against the folder
   listing. Highest-`priority` match wins; family tag is set.
2. For each file in the folder, all `layer: content` rules whose
   `path_glob` matches the file path evaluate. Multiple content rules
   may succeed (different field sets merge; later-priority wins on
   key collision).
3. The result is a `(family, fields)` tuple written to `stealer.victims`
   and `stealer.infections`.

File-path matching: content rules carry an optional top-level
`path_glob` (gitignore-style globs, matched against the path relative
to the victim folder root). Default: `**/*`.

---

## 8. Validation

- JSON Schema: `eyenet/stealer/rules/schema.json` (produced alongside
  this spec). Rules that fail schema validation are rejected at load.
- Golden-test fixtures: `tests/fixtures/stealer_rules/<rule_id>/` holds
  `input.txt` (or `input.json`, etc.) + `expected.json`. CI runs every
  rule against its fixture; a diff fails the build.
- Parity: the Python engine (pipeline) and the TypeScript engine
  (browser workbench) MUST produce byte-identical `expected.json` from
  the same fixture. A dedicated parity test runs both engines over the
  full fixture set.

---

## 9. Hot reload

The pipeline subscribes to SIGHUP. On receipt it re-reads
`/etc/eyenet/rules/stealer/*.yaml`, validates each against the schema,
and atomically swaps the rule set. A validation failure leaves the
previous rule set in place and logs the offending file.

In-flight work continues on the old rule set; new work picks up the new
set. There is no mid-archive swap.

---

## 10. Non-goals (v1)

- Recursive / nested matching (a JSON path extracting another JSON blob
  is not auto-re-parsed; write a second rule).
- User-defined normalize verbs. The catalog in section 6 is closed.
- Cross-file correlation inside the DSL. That's downstream aggregation
  in ClickHouse.
- Writeback. Rules are pure; they cannot mutate inputs or produce side
  effects beyond the `(family, fields)` tuple.
