// Per-type matchers. Each returns either a fields dict (match) or null
// (no match). Container matchers (folder) return {} on match, null otherwise.
//
// All eight DSL types are implemented. Parity contract: every matcher's
// output on a given input MUST equal the Python engine's output on the
// same input.
//
// RE2: operator-authored patterns go through re2js, a pure-JS port of
// Google's RE2 with the same linear-time DFA/NFA guarantee (no ReDoS).
// Python side uses google-re2; parity between the two bindings is enforced
// by the golden fixtures. We traded the WASM memory cap for Vite-friendly
// loading; the workbench runs single-folder at a time, so a pathological
// COMPILE that blows memory would only hang the local tab.
// YAML: js-yaml's safe `load` is the safe_load-equivalent entry point
// (YAML 1.2 CFG subset, no custom tags).

import { RE2JS } from 're2js';
import { load as yamlLoad } from 'js-yaml';

function _re2Compile(pattern, { multiline = false, dotall = false } = {}) {
  let flags = 0;
  if (multiline) flags |= RE2JS.MULTILINE;
  if (dotall) flags |= RE2JS.DOTALL;
  return RE2JS.compile(pattern, flags);
}

/** @typedef {import('./types.js').RuleSpec} RuleSpec */
/** @typedef {import('./types.js').MatchSpec} MatchSpec */
/** @typedef {import('./types.js').ExtractSpec} ExtractSpec */
/** @typedef {import('./types.js').ContentInput} ContentInput */
/** @typedef {import('./types.js').ContainerInput} ContainerInput */

/* ------------------------------------------------------------------ */
/*  L1 container                                                       */
/* ------------------------------------------------------------------ */

/**
 * @param {import('./types.js').FolderMatch} m
 * @param {ContainerInput} input
 * @returns {Record<string,string|number>|null}
 */
export function matchFolder(m, input) {
  const set = new Set(input.paths);
  for (const r of m.requires ?? []) if (!hasPath(set, r)) return null;
  for (const f of m.forbids ?? []) if (hasPath(set, f)) return null;
  const req = (m.requires ?? []).length;
  const opt = (m.optional ?? []).filter((p) => hasPath(set, p)).length;
  const minScore = m.min_score ?? req;
  return req + opt >= minScore ? {} : null;
}

/** Treat a trailing slash as a directory prefix (subtree membership). */
function hasPath(set, p) {
  if (p.endsWith('/')) {
    for (const x of set) if (x.startsWith(p)) return true;
    return false;
  }
  return set.has(p);
}

/* ------------------------------------------------------------------ */
/*  L3 content                                                         */
/* ------------------------------------------------------------------ */

/**
 * @param {import('./types.js').RegexMatch} m
 * @param {ExtractSpec|undefined} ex
 * @param {ContentInput} input
 */
export function matchRegex(m, ex, input) {
  let re;
  try {
    re = _re2Compile(m.pattern, { multiline: m.multiline, dotall: m.dotall });
  } catch {
    return null;
  }
  let matcher;
  try {
    matcher = re.matcher(input.text);
    if (!matcher.find()) return null;
  } catch {
    return null;
  }
  let groups;
  try { groups = matcher.getNamedGroups(); }
  catch { groups = {}; }
  if (!groups || Object.keys(groups).length === 0) return {};
  const want = ex?.fields ?? Object.keys(groups);
  /** @type {Record<string,string>} */
  const out = {};
  for (const k of want) if (groups[k] !== undefined && groups[k] !== null) out[k] = groups[k];
  return out;
}

/**
 * @param {import('./types.js').TemplateMatch} m
 * @param {ExtractSpec|undefined} ex
 * @param {ContentInput} input
 */
export function matchTemplate(m, ex, input) {
  // Compile fixed literals + named holes into a non-greedy regex.
  const holes = [];
  const compiled = m.template.replace(/\{(\w+)\}|([^{]+)/g, (_, hole, lit) => {
    if (hole) {
      holes.push(hole);
      return `(?<${hole}>.*?)`;
    }
    return lit.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  });
  return matchRegex(
    { type: 'regex', pattern: '^' + compiled + '$', multiline: m.multiline, dotall: true },
    ex ?? { fields: holes },
    input
  );
}

/**
 * @param {import('./types.js').DelimiterMatch} m
 * @param {ExtractSpec|undefined} ex
 * @param {ContentInput} input
 */
export function matchDelimiter(m, ex, input) {
  const lines = input.text.split(/\r?\n/);
  const cols = ex?.columns ?? {};
  /** @type {Record<string,string>|null} */
  let first = null;
  for (const line of lines) {
    if (m.skip_blank !== false && line.trim() === '') continue;
    if (m.skip_comment_prefix && line.startsWith(m.skip_comment_prefix)) continue;
    const parts = line.split(m.separator);
    if (m.min_columns && parts.length < m.min_columns) continue;
    const row = /** @type {Record<string,string>} */ ({});
    for (const [idxStr, field] of Object.entries(cols)) {
      const i = Number.parseInt(idxStr, 10);
      if (i < parts.length) row[field] = parts[i];
    }
    if (!first) first = row;
  }
  return first;
}

/**
 * @param {import('./types.js').JsonMatch} m
 * @param {ExtractSpec|undefined} ex
 * @param {ContentInput} input
 */
export function matchJson(m, ex, input) {
  let doc;
  try {
    doc = JSON.parse(input.text);
  } catch {
    return null;
  }
  if (!doc || typeof doc !== 'object') return null;
  for (const k of m.requires_keys ?? []) if (!(k in doc)) return null;
  return extractPaths(doc, ex?.paths ?? {});
}

/**
 * @param {import('./types.js').YamlMatch} m
 * @param {ExtractSpec|undefined} ex
 * @param {ContentInput} input
 */
export function matchYaml(m, ex, input) {
  let doc;
  try {
    // js-yaml's default schema is the safe one: JSON-equivalent tag subset,
    // no code execution, no !!js/function. Equivalent to Python's safe_load.
    doc = yamlLoad(input.text);
  } catch {
    return null;
  }
  if (!doc || typeof doc !== 'object' || Array.isArray(doc)) return null;
  for (const k of m.requires_keys ?? []) if (!(k in doc)) return null;
  return extractPaths(doc, ex?.paths ?? {});
}

/**
 * @param {import('./types.js').KeyvalueMatch} m
 * @param {ExtractSpec|undefined} ex
 * @param {ContentInput} input
 */
export function matchKeyvalue(m, ex, input) {
  /** @type {Record<string,string>} */
  const kv = {};
  for (const line of input.text.split(/\r?\n/)) {
    const i = line.indexOf(m.separator);
    if (i <= 0) continue;
    let k = line.slice(0, i);
    let v = line.slice(i + m.separator.length);
    if (m.strip_whitespace !== false) {
      k = k.replace(/^\s+|\s+$/g, '');
      v = v.replace(/^\s+|\s+$/g, '');
    }
    if (k) kv[k.toLowerCase()] = v;
  }
  for (const k of m.requires_keys ?? []) if (!(k.toLowerCase() in kv)) return null;
  /** @type {Record<string,string>} */
  const out = {};
  for (const [src, dst] of Object.entries(ex?.keys ?? {})) {
    const hit = kv[src.toLowerCase()];
    if (hit !== undefined) out[dst] = hit;
  }
  return out;
}

/**
 * @param {import('./types.js').KeyvalueIniMatch} m
 * @param {ExtractSpec|undefined} ex
 * @param {ContentInput} input
 */
export function matchKeyvalueIni(m, ex, input) {
  /** @type {Record<string,Record<string,string>>} */
  const sections = {};
  let cur = '';
  for (const raw of input.text.split(/\r?\n/)) {
    const line = raw.replace(/^\s+|\s+$/g, '');
    if (!line || line.startsWith(';') || line.startsWith('#')) continue;
    if (line.startsWith('[') && line.endsWith(']')) {
      cur = line.slice(1, -1);
      sections[cur] ??= {};
      continue;
    }
    const i = line.indexOf('=');
    if (i <= 0) continue;
    const k = line.slice(0, i).replace(/^\s+|\s+$/g, '');
    const v = line.slice(i + 1).replace(/^\s+|\s+$/g, '');
    sections[cur] ??= {};
    sections[cur][k] = v;
  }
  for (const s of m.requires_sections ?? []) if (!(s in sections)) return null;
  /** @type {Record<string,string>} */
  const out = {};
  for (const [dotted, dst] of Object.entries(ex?.keys ?? {})) {
    const dot = dotted.indexOf('.');
    if (dot <= 0) continue;
    const sec = dotted.slice(0, dot);
    const key = dotted.slice(dot + 1);
    const hit = sections[sec]?.[key];
    if (hit !== undefined) out[dst] = hit;
  }
  return out;
}

/* ------------------------------------------------------------------ */
/*  JSONPath-lite: $.a.b[0].c                                          */
/* ------------------------------------------------------------------ */

/**
 * @param {any} doc
 * @param {Record<string,string>} paths
 */
function extractPaths(doc, paths) {
  /** @type {Record<string,string|number>} */
  const out = {};
  for (const [field, expr] of Object.entries(paths)) {
    const v = evalPath(doc, expr);
    // Drop missing, null, and non-finite numeric values. In a forensic
    // context an extracted null means "no observation", not
    // "observation of null"; Infinity/NaN would both JSON.stringify to
    // "null" and crash Python's json.dumps on the parity side.
    if (v === null || v === undefined) continue;
    if (typeof v === 'number' && !Number.isFinite(v)) continue;
    if (typeof v === 'string' || typeof v === 'number') {
      out[field] = v;
    } else if (typeof v === 'boolean') {
      out[field] = JSON.stringify(v);  // "true" / "false"
    } else {
      out[field] = JSON.stringify(v);
    }
  }
  return out;
}

/** @param {any} doc @param {string} expr */
function evalPath(doc, expr) {
  if (!expr.startsWith('$')) return undefined;
  let cur = doc;
  const rest = expr.slice(1);
  for (const tok of rest.matchAll(/\.(\w+)|\[(\d+)\]/g)) {
    if (cur == null) return undefined;
    cur = tok[1] !== undefined ? cur[tok[1]] : cur[Number.parseInt(tok[2], 10)];
  }
  return cur;
}
