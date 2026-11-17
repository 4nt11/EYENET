// Engine orchestrator: run a rule set over a folder tree.
//
// Shape of use:
//   const rules = loadRules(yamlTexts);     // elsewhere (rule-loader)
//   const result = runRules(rules, folder); // this file
//
// `folder` is a VictimFolder: a list of (path, text) pairs. Nothing
// here touches the filesystem or the DOM. The workbench UI wraps this
// with FileSystemAccess / drag-drop plumbing.

import { RE2JS } from 're2js';

import { applyNormalize } from './normalize.js';
import {
  matchFolder,
  matchRegex,
  matchTemplate,
  matchDelimiter,
  matchJson,
  matchYaml,
  matchKeyvalue,
  matchKeyvalueIni
} from './matchers.js';


/** @typedef {import('./types.js').RuleSpec} RuleSpec */
/** @typedef {import('./types.js').EvalResult} EvalResult */
/** @typedef {import('./types.js').ContentInput} ContentInput */
/** @typedef {import('./types.js').ContainerInput} ContainerInput */

/**
 * @typedef {object} VictimFolder
 * @property {string} rootName
 * @property {ContentInput[]} files   - paths relative to rootName
 */

/**
 * @typedef {object} RunResult
 * @property {string|null} family                - L1 winning family tag
 * @property {Record<string,string|number>} fields - merged L3 extraction
 * @property {EvalResult[]} evaluations         - per-rule trace (for workbench UX)
 */

/**
 * @param {RuleSpec[]} rules
 * @param {VictimFolder} folder
 * @returns {RunResult}
 */
export function runRules(rules, folder) {
  /** @type {EvalResult[]} */
  const evaluations = [];
  const containerInput = { paths: folder.files.map((f) => f.path) };

  // L1: container rules, highest priority winner.
  /** @type {EvalResult|null} */
  let winner = null;
  for (const r of rules) {
    if (r.layer !== 'container') continue;
    const ev = evalRule(r, { kind: 'container', input: containerInput });
    evaluations.push(ev);
    if (ev.matched && (!winner || r.priority > winner.priority)) winner = ev;
  }
  const family = winner?.family ?? null;

  // L3: content rules. Later-priority wins on key collisions.
  const contentRules = rules
    .filter((r) => r.layer === 'content')
    .sort((a, b) => a.priority - b.priority);

  /** @type {Record<string,string|number>} */
  const merged = {};
  for (const r of contentRules) {
    // Optional opt-in family filter. Used by fallback rules (e.g. the
    // combolist probes) that must not fire inside a real stealer folder.
    if (r.requires_container_family != null && r.requires_container_family !== family) continue;
    const glob = r.path_glob ?? '**/*';
    for (const file of folder.files) {
      if (!matchGlob(glob, file.path)) continue;
      const ev = evalRule(r, { kind: 'content', input: file });
      evaluations.push(ev);
      if (ev.matched && ev.fields) Object.assign(merged, ev.fields);
    }
  }

  return { family, fields: merged, evaluations };
}

/**
 * @param {RuleSpec} r
 * @param {{kind:'container', input: ContainerInput} | {kind:'content', input: ContentInput}} env
 * @returns {EvalResult}
 */
function evalRule(r, env) {
  const base = { rule_id: r.id, layer: r.layer, family: r.family, priority: r.priority };
  /** @type {Record<string,string|number>|null} */
  let fields = null;

  if (env.kind === 'container') {
    if (r.match.type !== 'folder') {
      return { ...base, matched: false, reason: 'container rule requires folder match' };
    }
    fields = matchFolder(r.match, env.input);
  } else {
    switch (r.match.type) {
      case 'regex':        fields = matchRegex(r.match, r.extract, env.input); break;
      case 'template':     fields = matchTemplate(r.match, r.extract, env.input); break;
      case 'delimiter':    fields = matchDelimiter(r.match, r.extract, env.input); break;
      case 'json':         fields = matchJson(r.match, r.extract, env.input); break;
      case 'yaml':         fields = matchYaml(r.match, r.extract, env.input); break;
      case 'keyvalue':     fields = matchKeyvalue(r.match, r.extract, env.input); break;
      case 'keyvalue_ini': fields = matchKeyvalueIni(r.match, r.extract, env.input); break;
      case 'folder':
        return { ...base, matched: false, reason: 'folder match only valid in container layer' };
    }
  }

  if (fields === null) return { ...base, matched: false, reason: 'no match' };

  const mapped = applyMap(fields, r.map);
  const rej = ruleRejects(r, mapped);
  if (rej !== null) return { ...base, matched: false, reason: `reject: ${rej}` };
  const normed = r.normalize ? applyNormalize(mapped, r.normalize) : mapped;
  return { ...base, matched: true, fields: escapeNulls(normed) };
}

// First reject_pattern that matches any extracted value, or null if clean.
// re2js (ReDoS-safe, linear time). Applied AFTER map and BEFORE normalize
// so raw banner/null-sentinel text is caught before any transform.
function ruleRejects(r, fields) {
  const patterns = r.reject_patterns ?? [];
  if (patterns.length === 0) return null;
  const compiled = [];
  for (const p of patterns) {
    try { compiled.push(RE2JS.compile(p)); }
    catch { return null; }  // bad pattern = no reject (fail-open; load-time validates)
  }
  for (const v of Object.values(fields)) {
    const s = String(v);
    for (let i = 0; i < compiled.length; i++) {
      try { if (compiled[i].matcher(s).find()) return patterns[i]; }
      catch { /* keep scanning */ }
    }
  }
  return null;
}

// Replace raw NUL (U+0000) in string values with the literal 4-char escape
// '\x00'. Lossless: round-trips, stays searchable, surfaces an injected null
// to the analyst instead of hiding it. Applied after normalize so truncate
// operates on the original length. Nested-object values arrived as JSON
// blobs where JSON.stringify already encoded any inner null as '\u0000', so
// the raw-NUL check won't fire on them; parity with Python is preserved.
function escapeNulls(fields) {
  /** @type {Record<string,string|number>} */
  const out = {};
  for (const [k, v] of Object.entries(fields)) {
    out[k] = typeof v === 'string' && v.includes('\x00') ? v.replace(/\x00/g, '\\x00') : v;
  }
  return out;
}

/**
 * @param {Record<string,string|number>} fields
 * @param {import('./types.js').MapSpec|undefined} m
 */
function applyMap(fields, m) {
  if (!m) return fields;
  /** @type {Record<string,string|number>} */
  const out = {};
  const drop = new Set(m._drop ?? []);
  const rename = m.rename ?? /** @type {Record<string,string>} */ ({});
  for (const [k, v] of Object.entries(fields)) {
    if (drop.has(k)) continue;
    out[rename[k] ?? k] = v;
  }
  return out;
}

/**
 * gitignore-style glob matching: `**` matches any path segments,
 * `*` matches any chars except `/`, `?` matches one non-`/` char.
 * @param {string} glob @param {string} path
 */
export function matchGlob(glob, path) {
  const re = '^' + glob
    .replace(/[.+^${}()|[\]\\]/g, '\\$&')
    .replace(/\*\*/g, '::GLOBSTAR::')
    .replace(/\*/g, '[^/]*')
    .replace(/\?/g, '[^/]')
    .replace(/::GLOBSTAR::/g, '.*') + '$';
  return new RegExp(re).test(path);
}
