// Per-type matchers. Each returns either a fields dict (match) or null
// (no match). Container matchers (folder) return {} on match, null otherwise.
//
// All eight DSL types are implemented. Parity contract: every matcher's
// output on a given input MUST equal the Python engine's output on the
// same input.
//
// RE2: operator-authored patterns go through AdGuard's RE2-wasm fork, which
// gives us RE2's linear-time guarantee PLUS a per-pattern memory cap so a
// pathological pattern can't blow the WASM heap at compile time. Default
// cap is 8 MB per regex (plenty for extraction patterns, still bounded).
// YAML: js-yaml's safe `load` is the safe_load-equivalent entry point
// (YAML 1.2 CFG subset, no custom tags).

import { RE2 } from '@adguard/re2-wasm';
import { load as yamlLoad } from 'js-yaml';

const RE2_MAX_MEM = 8 * 1024 * 1024;

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
  const flags = 'u' + (m.multiline ? 'm' : '') + (m.dotall ? 's' : '');
  let re;
  try {
    re = new RE2(m.pattern, flags, RE2_MAX_MEM);
  } catch {
    return null;
  }
  let hit;
  try {
    hit = re.exec(input.text);
  } catch {
    return null;  // maxMem exceeded or match-time failure
  }
  if (!hit) return null;
  if (!hit.groups) return {};
  const want = ex?.fields ?? Object.keys(hit.groups);
  /** @type {Record<string,string>} */
  const out = {};
  for (const k of want) if (hit.groups[k] !== undefined) out[k] = hit.groups[k];
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
