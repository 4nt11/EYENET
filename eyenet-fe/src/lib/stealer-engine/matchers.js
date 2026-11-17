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
 * Folder matcher. Two authoring styles: a flat `requires/forbids/
 * optional/min_score` shape (v1 sugar) and a predicate tree (v2, real
 * boolean algebra). The flat style is lowered to an equivalent tree at
 * evaluation time so the engine only ever walks one code path.
 * @param {import('./types.js').FolderMatch} m
 * @param {ContainerInput} input
 * @returns {Record<string,string|number>|null}
 */
export function matchFolder(m, input) {
  const set = new Set(input.paths);
  const list = input.paths;
  const pred = m.predicate ?? lowerLegacyFolder(m);
  try {
    return evalPredicate(pred, set, list) ? {} : null;
  } catch (e) {
    // Fail-safe: a broken predicate warns but doesn't crash evaluation.
    console.warn('folder predicate rejected:', e?.message ?? e);
    return null;
  }
}

/** Treat a trailing slash as a directory prefix (subtree membership). */
function hasPath(set, p) {
  if (p.endsWith('/')) {
    for (const x of set) if (x.startsWith(p)) return true;
    return false;
  }
  return set.has(p);
}

/**
 * Walk a predicate tree. Each node is a single-key dict naming the
 * operator. Operators: and / or / xor / not / at_least / exactly /
 * at_most. Leaves: path / glob.
 */
function evalPredicate(node, set, list) {
  if (!node || typeof node !== 'object' || Array.isArray(node) || Object.keys(node).length !== 1) {
    throw new Error(`predicate node must be a single-key dict: ${JSON.stringify(node)}`);
  }
  const op = Object.keys(node)[0];
  const body = node[op];
  switch (op) {
    case 'and':
      if (!Array.isArray(body)) throw new Error("'and' expects a list");
      return body.every((c) => evalPredicate(c, set, list));
    case 'or':
      if (!Array.isArray(body)) throw new Error("'or' expects a list");
      return body.some((c) => evalPredicate(c, set, list));
    case 'xor': {
      if (!Array.isArray(body)) throw new Error("'xor' expects a list");
      // Odd-parity, matches standard digital logic.
      let trues = 0;
      for (const c of body) if (evalPredicate(c, set, list)) trues++;
      return trues % 2 === 1;
    }
    case 'not':
      return !evalPredicate(body, set, list);
    case 'at_least':
    case 'exactly':
    case 'at_most': {
      if (!body || typeof body !== 'object' || !Array.isArray(body.of)) {
        throw new Error(`'${op}' expects {count, of: [...]}`);
      }
      const count = body.count ?? 0;
      if (!Number.isInteger(count) || count < 0) {
        throw new Error(`'${op}' count must be a non-negative integer`);
      }
      let hits = 0;
      for (const c of body.of) if (evalPredicate(c, set, list)) hits++;
      if (op === 'at_least') return hits >= count;
      if (op === 'at_most') return hits <= count;
      return hits === count;
    }
    case 'path':
      if (typeof body !== 'string') throw new Error("'path' expects a string");
      return hasPath(set, body);
    case 'glob':
      if (typeof body !== 'string') throw new Error("'glob' expects a string");
      // Local import via dynamic reference to avoid a cycle at module init.
      return list.some((p) => matchGlobLocal(body, p));
    default:
      throw new Error(`unknown predicate operator: ${op}`);
  }
}

/**
 * Sugar lowering: translate the flat requires/forbids/optional/min_score
 * shape to an equivalent predicate tree.
 */
function lowerLegacyFolder(m) {
  const requires = m.requires ?? [];
  const forbids = m.forbids ?? [];
  const optional = m.optional ?? [];
  const minScore = m.min_score ?? requires.length;
  /** @type {object[]} */
  const clauses = [];
  for (const r of requires) clauses.push({ path: r });
  for (const f of forbids) clauses.push({ not: { path: f } });
  if (minScore > 0 && (requires.length || optional.length)) {
    clauses.push({
      at_least: {
        count: minScore,
        of: [...requires, ...optional].map((p) => ({ path: p }))
      }
    });
  }
  return clauses.length === 0 ? { and: [] } : { and: clauses };
}

// matchGlob lives in engine.js; this is the same algorithm reimplemented
// here to avoid an import cycle. Behaviour is byte-parity with engine.matchGlob.
function matchGlobLocal(glob, path) {
  const re = '^' + glob
    .replace(/[.+^${}()|[\]\\]/g, '\\$&')
    .replace(/\*\*/g, '::GLOBSTAR::')
    .replace(/\*/g, '[^/]*')
    .replace(/\?/g, '[^/]')
    .replace(/::GLOBSTAR::/g, '.*') + '$';
  return new RegExp(re).test(path);
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
  for (const row of iterDelimiter(m, ex, input.text)) return row;
  return null;
}

// Iterator used by matchDelimiter (takes first row) and by bulkParse
// (walks every row). Centralised so a tweak lands once and parity stays
// tight.
export function* iterDelimiter(m, ex, text) {
  const cols = ex?.columns ?? {};
  for (const line of text.split(/\r?\n/)) {
    if (m.skip_blank !== false && line.trim() === '') continue;
    if (m.skip_comment_prefix && line.startsWith(m.skip_comment_prefix)) continue;
    const parts = line.split(m.separator);
    if (m.min_columns && parts.length < m.min_columns) continue;
    /** @type {Record<string,string>} */
    const row = {};
    for (const [idxStr, field] of Object.entries(cols)) {
      const i = Number.parseInt(idxStr, 10);
      if (i < parts.length) row[field] = parts[i];
    }
    yield row;
  }
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
/**
 * Valve Data Format (Steam's .vdf) matcher. Parses the KeyValues tree,
 * honours requires_keys on the top level, extracts via JSONPath-lite.
 * When `pivot` is set, iterates each child of the pivot as a record
 * (bulk-friendly); match_vdf itself returns the first record.
 */
export function matchVdf(m, ex, input) {
  let doc;
  try { doc = parseVdf(input.text); }
  catch { return null; }
  if (!doc || typeof doc !== 'object') return null;
  for (const k of m.requires_keys ?? []) if (!(k in doc)) return null;
  if (m.pivot) {
    for (const [key, value] of pivotChildren(doc, m.pivot)) {
      return extractVdfRecord(value, key, ex?.paths ?? {});
    }
    return null;
  }
  return extractPathsVdf(doc, ex?.paths ?? {});
}

/** Generator used by bulkParse: walk every pivot child as a record. */
export function* iterVdf(m, ex, text) {
  let doc;
  try { doc = parseVdf(text); }
  catch { return; }
  if (!doc || typeof doc !== 'object') return;
  for (const k of m.requires_keys ?? []) if (!(k in doc)) return;
  if (!m.pivot) {
    yield extractPathsVdf(doc, ex?.paths ?? {});
    return;
  }
  const paths = ex?.paths ?? {};
  for (const [key, value] of pivotChildren(doc, m.pivot)) {
    yield extractVdfRecord(value, key, paths);
  }
}

function* pivotChildren(doc, pivotExpr) {
  if (!pivotExpr.startsWith('$')) return;
  let cur = doc;
  const rest = pivotExpr.slice(1);
  for (const tok of rest.matchAll(/\.(\w+)|\[(\d+)\]/g)) {
    if (cur == null || typeof cur !== 'object') return;
    cur = tok[1] !== undefined ? cur[tok[1]] : null; // numeric index invalid for VDF
    if (cur == null) return;
  }
  if (cur && typeof cur === 'object' && !Array.isArray(cur)) {
    for (const [k, v] of Object.entries(cur)) yield [k, v];
  }
}

function extractVdfRecord(value, keyName, paths) {
  const out = {};
  for (const [field, expr] of Object.entries(paths)) {
    if (expr === '$key') { out[field] = keyName; continue; }
    const v = evalPathLocal(value, expr);
    if (v == null) continue;
    if (typeof v === 'string' || typeof v === 'number') out[field] = v;
    else out[field] = JSON.stringify(v);
  }
  return out;
}

function extractPathsVdf(doc, paths) {
  const out = {};
  for (const [field, expr] of Object.entries(paths)) {
    const v = evalPathLocal(doc, expr);
    if (v == null) continue;
    if (typeof v === 'string') out[field] = v;
    else out[field] = JSON.stringify(v);
  }
  return out;
}

function evalPathLocal(doc, expr) {
  if (!expr?.startsWith('$')) return null;
  let cur = doc;
  for (const tok of expr.slice(1).matchAll(/\.(\w+)|\[(\d+)\]/g)) {
    if (cur == null || typeof cur !== 'object') return null;
    cur = tok[1] !== undefined ? cur[tok[1]] : null;
  }
  return cur;
}

// VDF parser. KeyValues: alternating "key" + ("value" | { nested }) pairs.
// Quoted strings with \" \\ \n \t escapes. '//' line comments. No arrays;
// duplicate keys are last-wins when flattened (matches Steam behaviour).
function parseVdf(text) {
  const p = { text, i: 0, n: text.length };
  const out = {};
  for (;;) {
    skipWS(p);
    if (p.i >= p.n) break;
    const key = readStr(p);
    skipWS(p);
    if (p.i >= p.n) throw new Error(`dangling key ${key} at eof`);
    if (p.text[p.i] === '{') { p.i++; out[key] = readObj(p); }
    else out[key] = readStr(p);
  }
  return out;
}

function readObj(p) {
  const obj = {};
  for (;;) {
    skipWS(p);
    if (p.i >= p.n) throw new Error('unterminated object');
    if (p.text[p.i] === '}') { p.i++; return obj; }
    const key = readStr(p);
    skipWS(p);
    if (p.i >= p.n) throw new Error(`dangling key ${key} inside object`);
    if (p.text[p.i] === '{') { p.i++; obj[key] = readObj(p); }
    else obj[key] = readStr(p);
  }
}

function readStr(p) {
  if (p.i >= p.n) throw new Error('expected string at eof');
  if (p.text[p.i] === '"') {
    p.i++;
    let out = '';
    while (p.i < p.n) {
      const ch = p.text[p.i];
      if (ch === '\\' && p.i + 1 < p.n) {
        const nxt = p.text[p.i + 1];
        out += nxt === 'n' ? '\n' : nxt === 't' ? '\t' : nxt === 'r' ? '\r' : nxt;
        p.i += 2; continue;
      }
      if (ch === '"') { p.i++; return out; }
      out += ch; p.i++;
    }
    throw new Error('unterminated quoted string');
  }
  const start = p.i;
  while (p.i < p.n && !' \t\r\n{}"'.includes(p.text[p.i])) p.i++;
  if (p.i === start) throw new Error(`expected string at ${p.i}`);
  return p.text.slice(start, p.i);
}

function skipWS(p) {
  while (p.i < p.n) {
    const ch = p.text[p.i];
    if (ch === ' ' || ch === '\t' || ch === '\r' || ch === '\n') { p.i++; continue; }
    if (ch === '/' && p.i + 1 < p.n && p.text[p.i + 1] === '/') {
      while (p.i < p.n && p.text[p.i] !== '\n') p.i++;
      continue;
    }
    return;
  }
}

// --------------------------------------------------------------------- //
//  XML (hardened in-tree parser)                                         //
// --------------------------------------------------------------------- //
// No DOCTYPE. No entity expansion beyond the five standard XML entities
// plus &#NN; and &#xHH; numeric refs. No PI resolution (<?...?> is
// skipped unread). No namespace resolution. Depth cap 256. The parser
// is hand-rolled so there is no fetch / no DOM reachability / no DTD
// grammar to subvert. Byte-parity with the Python and Go ports.

const XML_MAX_DEPTH = 256;
const XML_ENTITIES = { lt: '<', gt: '>', amp: '&', quot: '"', apos: "'" };

class XMLParseError extends Error {}

export function matchXml(m, ex, input) {
  let root;
  try { root = parseXml(input.text); } catch { return null; }
  if (!checkXmlRequires(root, m.requires_keys ?? [])) return null;
  const paths = ex?.paths ?? {};
  if (m.pivot) {
    for (const [key, el] of xmlPivotChildren(root, m.pivot)) {
      return xmlExtractRecord(el, key, paths);
    }
    return null;
  }
  return xmlExtractRecord(root, root.name, paths);
}

export function* iterXml(m, ex, text) {
  let root;
  try { root = parseXml(text); } catch { return; }
  if (!checkXmlRequires(root, m.requires_keys ?? [])) return;
  const paths = ex?.paths ?? {};
  if (!m.pivot) { yield xmlExtractRecord(root, root.name, paths); return; }
  for (const [key, el] of xmlPivotChildren(root, m.pivot)) {
    yield xmlExtractRecord(el, key, paths);
  }
}

function checkXmlRequires(root, required) {
  if (required.length === 0) return true;
  const top = new Set([root.name, ...root.children.map((c) => c.name)]);
  return required.every((k) => top.has(k));
}

function* xmlPivotChildren(root, pivotExpr) {
  if (!pivotExpr.startsWith('$')) return;
  const steps = [];
  for (const tok of pivotExpr.slice(1).matchAll(/\.(\w+)/g)) steps.push(tok[1]);
  if (steps.length === 0) return;
  let cur = root;
  let rest = steps[0] === root.name ? steps.slice(1) : steps;
  const target = rest.pop();
  for (const step of rest) {
    cur = cur.children.find((c) => c.name === step);
    if (!cur) return;
  }
  for (const c of cur.children) if (c.name === target) yield [c.name, c];
}

function xmlExtractRecord(el, keyName, paths) {
  const out = {};
  for (const [field, expr] of Object.entries(paths)) {
    if (expr === '$key') { out[field] = keyName; continue; }
    const v = xmlEvalPath(el, expr);
    if (v == null) continue;
    out[field] = v;
  }
  return out;
}

function xmlEvalPath(el, expr) {
  if (!expr?.startsWith('$')) return null;
  let attr = null;
  if (expr.includes('@')) {
    const i = expr.lastIndexOf('@');
    attr = expr.slice(i + 1);
    expr = expr.slice(0, i);
  }
  let cur = el;
  for (const tok of expr.slice(1).matchAll(/\.(\w+)/g)) {
    const next = cur.children.find((c) => c.name === tok[1]);
    if (!next) return null;
    cur = next;
  }
  if (attr != null) return cur.attrs[attr] ?? null;
  return cur.text;
}

function parseXml(text) {
  const p = { t: text, i: 0, n: text.length, depth: 0 };
  skipProlog(p);
  if (p.i >= p.n || p.t[p.i] !== '<') throw new XMLParseError('no root element');
  return parseElement(p);
}

function skipProlog(p) {
  for (;;) {
    while (p.i < p.n && /\s/.test(p.t[p.i])) p.i++;
    if (p.t.startsWith('<?', p.i)) {
      const end = p.t.indexOf('?>', p.i + 2);
      if (end < 0) throw new XMLParseError('unterminated PI');
      p.i = end + 2; continue;
    }
    if (p.t.startsWith('<!--', p.i)) {
      const end = p.t.indexOf('-->', p.i + 4);
      if (end < 0) throw new XMLParseError('unterminated comment');
      p.i = end + 3; continue;
    }
    if (p.t.startsWith('<!DOCTYPE', p.i)) throw new XMLParseError('DOCTYPE not supported');
    return;
  }
}

function parseElement(p) {
  p.depth++;
  if (p.depth > XML_MAX_DEPTH) throw new XMLParseError(`depth > ${XML_MAX_DEPTH}`);
  if (p.t[p.i] !== '<') throw new XMLParseError(`expected '<' at ${p.i}`);
  p.i++;
  const name = readName(p);
  const el = { name, attrs: {}, children: [], text: '' };
  for (;;) {
    while (p.i < p.n && /\s/.test(p.t[p.i])) p.i++;
    if (p.i >= p.n) throw new XMLParseError(`unterminated start tag <${name}>`);
    if (p.t.startsWith('/>', p.i)) { p.i += 2; p.depth--; return el; }
    if (p.t[p.i] === '>') { p.i++; break; }
    const an = readName(p);
    while (p.i < p.n && /\s/.test(p.t[p.i])) p.i++;
    if (p.t[p.i] !== '=') throw new XMLParseError(`missing '=' after attr ${an}`);
    p.i++;
    while (p.i < p.n && /\s/.test(p.t[p.i])) p.i++;
    el.attrs[an] = readAttrValue(p);
  }
  const buf = [];
  for (;;) {
    if (p.i >= p.n) throw new XMLParseError(`unterminated <${name}>`);
    if (p.t.startsWith('</', p.i)) {
      p.i += 2;
      const closing = readName(p);
      while (p.i < p.n && /\s/.test(p.t[p.i])) p.i++;
      if (p.t[p.i] !== '>') throw new XMLParseError(`malformed close </${closing}>`);
      p.i++;
      if (closing !== name) throw new XMLParseError(`close </${closing}> != open <${name}>`);
      el.text = buf.join('');
      p.depth--;
      return el;
    }
    if (p.t.startsWith('<!--', p.i)) {
      const end = p.t.indexOf('-->', p.i + 4);
      if (end < 0) throw new XMLParseError('unterminated comment');
      p.i = end + 3; continue;
    }
    if (p.t.startsWith('<![CDATA[', p.i)) {
      const end = p.t.indexOf(']]>', p.i + 9);
      if (end < 0) throw new XMLParseError('unterminated CDATA');
      buf.push(p.t.slice(p.i + 9, end));
      p.i = end + 3; continue;
    }
    if (p.t.startsWith('<?', p.i)) {
      const end = p.t.indexOf('?>', p.i + 2);
      if (end < 0) throw new XMLParseError('unterminated PI');
      p.i = end + 2; continue;
    }
    if (p.t[p.i] === '<') { el.children.push(parseElement(p)); continue; }
    const end = p.t.indexOf('<', p.i);
    if (end < 0) throw new XMLParseError(`unterminated <${name}>`);
    buf.push(xmlUnescape(p.t.slice(p.i, end)));
    p.i = end;
  }
}

function readName(p) {
  const start = p.i;
  if (!/[A-Za-z_:]/.test(p.t[p.i])) throw new XMLParseError(`expected name at ${p.i}`);
  p.i++;
  while (p.i < p.n && /[A-Za-z0-9_\-.:]/.test(p.t[p.i])) p.i++;
  return p.t.slice(start, p.i);
}

function readAttrValue(p) {
  const q = p.t[p.i];
  if (q !== '"' && q !== "'") throw new XMLParseError('attr value not quoted');
  p.i++;
  const start = p.i;
  while (p.i < p.n && p.t[p.i] !== q) p.i++;
  if (p.i >= p.n) throw new XMLParseError('unterminated attr value');
  const v = xmlUnescape(p.t.slice(start, p.i));
  p.i++;
  return v;
}

function xmlUnescape(s) {
  if (!s.includes('&')) return s;
  const out = [];
  let i = 0;
  while (i < s.length) {
    if (s[i] !== '&') { out.push(s[i]); i++; continue; }
    const end = s.indexOf(';', i + 1);
    if (end < 0) { out.push('&'); i++; continue; }
    const name = s.slice(i + 1, end);
    if (name in XML_ENTITIES) out.push(XML_ENTITIES[name]);
    else if (name.startsWith('#x') || name.startsWith('#X')) {
      const cp = parseInt(name.slice(2), 16);
      out.push(Number.isFinite(cp) ? String.fromCodePoint(cp) : s.slice(i, end + 1));
    } else if (name.startsWith('#')) {
      const cp = parseInt(name.slice(1), 10);
      out.push(Number.isFinite(cp) ? String.fromCodePoint(cp) : s.slice(i, end + 1));
    } else {
      // Unknown named entity: preserve literally; do NOT resolve.
      out.push(s.slice(i, end + 1));
    }
    i = end + 1;
  }
  return out.join('');
}

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
