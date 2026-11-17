// Normalize verb catalog. Each verb is a pure string-to-string function
// applied to one field of the extracted dict. A verb that fails
// (parse error, no match) DROPS the field silently, per the spec.
//
// Parity: the Python engine implements the same seven verbs against
// the same inputs with the same outputs. Golden fixtures enforce it.
//
// replace_re2 runs through the same ReDoS-safe RE2 engine the matchers use.

import { RE2 } from '@adguard/re2-wasm';

const RE2_MAX_MEM = 8 * 1024 * 1024;

/** @typedef {import('./types.js').NormalizeStep} NormalizeStep */

/**
 * @param {Record<string, string|number>} fields
 * @param {NormalizeStep[]} steps
 * @returns {Record<string, string|number>}
 */
export function applyNormalize(fields, steps) {
  const out = { ...fields };
  for (const step of steps) {
    const v = out[step.field];
    if (v === undefined || v === null) continue;
    const raw = String(v);
    const next = runVerb(step, raw);
    if (next === undefined) {
      delete out[step.field];
    } else {
      out[step.field] = next;
    }
  }
  return out;
}

/**
 * @param {NormalizeStep} step
 * @param {string} raw
 * @returns {string|number|undefined}
 */
function runVerb(step, raw) {
  switch (step.verb) {
    case 'strip_whitespace':
      return raw.replace(/^\s+|\s+$/g, '');
    case 'lowercase':
      // ponytail: ASCII-only lowercase per spec; .toLowerCase() is locale-safe for ASCII.
      return raw.toLowerCase();
    case 'uppercase':
      return raw.toUpperCase();
    case 'truncate': {
      const n = step.max_len ?? 0;
      if (n <= 0) return raw;
      // ponytail: byte-length truncation via TextEncoder; UTF-8 safe boundary check later.
      return raw.length > n ? raw.slice(0, n) : raw;
    }
    case 'int_from_string': {
      const m = raw.match(/-?\d+/);
      if (!m) return undefined;
      const n = Number.parseInt(m[0], 10);
      return Number.isFinite(n) ? n : undefined;
    }
    case 'replace_re2': {
      if (!step.pattern) return raw;
      try {
        const re = new RE2(step.pattern, 'gu', RE2_MAX_MEM);
        return re.replace(raw, step.replacement ?? '');
      } catch {
        return undefined;
      }
    }
    case 'date_parse':
      return parseDate(raw, step.format ?? 'iso8601');
    default:
      return undefined;
  }
}

/**
 * @param {string} raw
 * @param {'iso8601'|'rfc2822'|'epoch_seconds'} format
 * @returns {string|undefined}
 */
function parseDate(raw, format) {
  if (format === 'epoch_seconds') {
    const n = Number.parseInt(raw, 10);
    if (!Number.isFinite(n)) return undefined;
    return trimFracSeconds(new Date(n * 1000).toISOString());
  }
  // iso8601 / rfc2822: Date.parse handles both; emit canonical ISO back.
  const t = Date.parse(raw);
  if (Number.isNaN(t)) return undefined;
  return trimFracSeconds(new Date(t).toISOString());
}

// Both engines drop fractional seconds before the trailing Z so the
// emitted ISO string is identical on both sides. Spec: date_parse
// always yields second-precision UTC.
function trimFracSeconds(iso) { return iso.replace(/\.\d+Z$/, 'Z'); }
