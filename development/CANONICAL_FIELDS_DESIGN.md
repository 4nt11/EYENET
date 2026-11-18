# Canonical field vocabulary for stealer records

## Problem

Extracted records carry a free-form `fields: Map<String, String>` dict whose
keys are whatever the rule author named in the capture group. Different rules
describe the same concept under different names:

- `environment_windows` emits `env_user_name`, `env_computer_name`
- `stealer_info_yaml` emits `os_user_name`, `os_computer_name`
- Legacy `pc_info_block` would have emitted `user`, `hostname`

The drawer System tab had to dump every field it saw as a flat k/v list, which
produced duplicate labels and leaked the rule-author's naming choices into the
operator UI. Credentials tab coalesces via ad-hoc `firstField(['url', 'host',
'target'])` lists maintained by hand in the page component.

## Decision (shipped in Phase 1)

A **canonical field layer** is applied at render time by the FE
(`eyenet-fe/src/lib/stealerCanonicalFields.js`). It declares the canonical
vocabulary per concept group (host, av, build, net, cred, cookie, proc,
software) and the alias list per canonical field. `canonicalize(records,
group)` collapses a records array into one `{canonical_key: value}` map,
first-alias-wins per key. The System drawer tab renders a clean machine
profile from this instead of the raw dict.

This bridges the UI without touching gotractor or the rule YAML. Every
operator who writes a new rule still gets to pick arbitrary capture names;
their fields show up correctly in the UI if those names are in the alias
list, and under "extras" if not.

## Decision (Phase 2, not yet shipped)

Move the mapping INTO the rule YAML as a per-rule `field_map` section and
make gotractor apply it at emit time, so `extracted_records.fields` carries
canonical keys directly. Downstream indexes, queries, and other consumers
can then rely on canonical names without going through a client-side layer.

### YAML shape

```yaml
rule_id: environment_windows
family: victim_environment
match:
  ...
field_map:
  env_computer_name: host.computer
  env_user_name:     host.user
  env_user_domain:   host.domain
  env_appdata:       host.appdata
  env_cpu_identifier: host.cpu
  env_cpu_arch:      host.cpu_arch
```

Rules declare their canonical mapping explicitly. gotractor validates every
RHS at catalog load against a canonical schema file
(`stealer_canonical_fields.yaml`, shipped in-tree). An unknown RHS fails the
load (loud, fast). An RHS not present in the schema is a typo or a missing
schema entry: the author either fixes the YAML or opens a PR to extend the
schema.

A capture with no field_map entry falls through to `extras.<raw_name>` so
rule authors can experiment without blocking emission.

### Wazuh-decoder parallel

Wazuh ships a fixed set of decoded fields (`srcip`, `srcuser`,
`program_name`, ...) and treats everything else as a free-form extra. We
adopt the same split: canonical keys for a known closed vocabulary, extras
for rule-author freedom. Dashboards, queries, and alerting key off the
canonical set. The catalog of canonical names lives in one file; growth is
a deliberate PR, not an accident of rule authorship.

### Migration path

1. Ship `stealer_canonical_fields.yaml` with the current vocabulary from
   `stealerCanonicalFields.js`. The two stay in sync; the FE module becomes
   generated-from-YAML or the backend-exposes-schema endpoint drives it.
2. Rules land `field_map` sections incrementally. Until a rule has one, it
   still emits raw keys; the FE canonicalization layer continues to coalesce
   on alias lists. Once every active rule has a `field_map`, the FE layer
   becomes a thin pass-through and can be removed.
3. Backend starts indexing canonical keys. `extracted_records.fields` keys
   become a stable universe suitable for sparse column projections if
   query perf ever needs them.

### Not in scope for Phase 2

- Typing. Every canonical value stays a `String`. Types are implicit per
  field (`host.ram` is "<N> MB", `build.elevated` is "true"/"false"). A
  future Phase 3 can add a types file if the UI starts needing date/number
  parsing at scale.
- Localized labels. `CANONICAL_LABELS` in the JS module is English-only.
- Versioning. If a canonical name needs to change meaning, add a new name
  and deprecate the old one via an alias (drop after one release cycle).

## Status

- Phase 1: shipped (FE render-time canonicalization layer + System tab
  rewrite).
- Phase 2: deferred until operator signs off on the canonical vocabulary
  listed in `stealerCanonicalFields.js`.
