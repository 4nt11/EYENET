// Golden fixture parity: every fixture in tests/fixtures/stealer_rules/
// must produce the same RunResult here as in test_parity_fixtures.py.
//
// Run:  node eyenet-fe/tests/stealer-engine.parity.mjs
// Exits 0 on success, non-zero on first divergence.

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { load as yamlLoad } from 'js-yaml';

import { runRules } from '../src/lib/stealer-engine/engine.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = resolve(HERE, '../../tests/fixtures/stealer_rules');

function loadFixture(fdir) {
  const rule = yamlLoad(readFileSync(resolve(fdir, 'rule.yaml'), 'utf8'));
  const expected = JSON.parse(readFileSync(resolve(fdir, 'expected.json'), 'utf8'));
  const inputs = readdirSync(fdir).filter((n) => n.startsWith('input.'));
  if (inputs.length !== 1) throw new Error(`${fdir}: want 1 input.*, got ${inputs.length}`);
  const path = rule.path_glob || inputs[0];
  const text = readFileSync(resolve(fdir, inputs[0]), 'utf8');
  return { rule, expected, file: { path, text } };
}

function canon(v) {
  // Stable stringify so ordering doesn't false-fail; mirrors the Python
  // harness's json.dumps(sort_keys=True).
  return JSON.stringify(v, Object.keys(v ?? {}).sort ? sortReplacer : undefined);
}

function sortReplacer(_key, value) {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return Object.keys(value).sort().reduce((o, k) => {
      o[k] = value[k];
      return o;
    }, {});
  }
  return value;
}

let failed = 0;
for (const name of readdirSync(FIXTURES).sort()) {
  const fdir = resolve(FIXTURES, name);
  if (!statSync(fdir).isDirectory()) continue;
  const { rule, expected, file } = loadFixture(fdir);
  const folder = { rootName: name, files: [file] };
  const result = runRules([rule], folder);
  const actual = { family: result.family, fields: result.fields };
  if (canon(actual) !== canon(expected)) {
    failed++;
    console.error(`[FAIL] ${name}`);
    console.error(`  actual:   ${canon(actual)}`);
    console.error(`  expected: ${canon(expected)}`);
  } else {
    console.log(`[ok]   ${name}`);
  }
}

if (failed) {
  console.error(`\n${failed} fixture(s) diverged`);
  process.exit(1);
}
console.log('\nparity: ok');
