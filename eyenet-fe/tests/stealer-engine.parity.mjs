// Golden fixture parity: every fixture in tests/fixtures/stealer_rules/
// must produce the same RunResult here as in test_parity_fixtures.py.
//
// Run:  node eyenet-fe/tests/stealer-engine.parity.mjs
// Exits 0 on success, non-zero on first divergence.

import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { load as yamlLoad } from 'js-yaml';

import { runRules } from '../src/lib/stealer-engine/engine.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = resolve(HERE, '../../tests/fixtures/stealer_rules');

function loadFixture(fdir) {
  // rule.yaml may be a single rule or a list (container + content pair).
  const raw = yamlLoad(readFileSync(resolve(fdir, 'rule.yaml'), 'utf8'));
  const rules = Array.isArray(raw) ? raw : [raw];
  const expected = JSON.parse(readFileSync(resolve(fdir, 'expected.json'), 'utf8'));

  // Two input styles: single input.* OR a full input_folder/ tree.
  const folderDir = resolve(fdir, 'input_folder');
  if (existsSync(folderDir) && statSync(folderDir).isDirectory()) {
    const files = [];
    const walk = (dir, prefix) => {
      for (const name of readdirSync(dir).sort()) {
        const abs = resolve(dir, name);
        const st = statSync(abs);
        const rel = prefix ? `${prefix}/${name}` : name;
        if (st.isDirectory()) walk(abs, rel);
        else files.push({ path: rel, text: readFileSync(abs, 'utf8') });
      }
    };
    walk(folderDir, '');
    return { rules, expected, files };
  }

  const inputs = readdirSync(fdir).filter((n) => n.startsWith('input.'));
  if (inputs.length !== 1) throw new Error(`${fdir}: want 1 input.* or input_folder/`);
  const contentRule = rules.find((r) => r.layer === 'content') ?? rules[0];
  const path = contentRule.path_glob || inputs[0];
  const text = readFileSync(resolve(fdir, inputs[0]), 'utf8');
  return { rules, expected, files: [{ path, text }] };
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
  const { rules, expected, files } = loadFixture(fdir);
  const folder = { rootName: name, files };
  const result = runRules(rules, folder);
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
