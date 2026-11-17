// Smoke: every matcher + normalize + orchestrator against a synthetic
// Lumma-ish victim folder. Run from a scratch route or the browser console:
//
//   import { selfTest } from '$lib/stealer-engine/_selftest.js';
//   selfTest();  // throws on any regression
//
// ponytail: no test framework; plain assertions. Keep this green when editing
// matchers; swap for golden fixtures once the Python engine lands.

import { runRules, matchGlob } from './engine.js';
import { applyNormalize } from './normalize.js';
import { matchKeyvalueIni, matchJson, matchYaml, matchRegex } from './matchers.js';

function eq(label, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g !== w) throw new Error(`[${label}] got ${g} want ${w}`);
}

export function selfTest() {
  // 1. normalize verbs
  eq('strip', applyNormalize({ a: '  x  ' }, [{ verb: 'strip_whitespace', field: 'a' }]), { a: 'x' });
  eq('lower', applyNormalize({ a: 'AB' }, [{ verb: 'lowercase', field: 'a' }]), { a: 'ab' });
  eq('upper', applyNormalize({ a: 'ab' }, [{ verb: 'uppercase', field: 'a' }]), { a: 'AB' });
  eq('trunc', applyNormalize({ a: 'abcdef' }, [{ verb: 'truncate', field: 'a', max_len: 3 }]), { a: 'abc' });
  eq('int', applyNormalize({ a: 'count: 42' }, [{ verb: 'int_from_string', field: 'a' }]), { a: 42 });
  eq('replace', applyNormalize({ a: 'a  b   c' }, [{ verb: 'replace_re2', field: 'a', pattern: '\\s+', replacement: ' ' }]), { a: 'a b c' });

  // 2. INI
  const iniHit = matchKeyvalueIni(
    { type: 'keyvalue_ini', requires_sections: ['Hardware'] },
    { keys: { 'Hardware.HWID': 'hwid', 'Software.OS': 'os' } },
    { path: 'information.txt', text: '[Hardware]\nHWID=ABC-123\n\n[Software]\nOS=Win10\n' }
  );
  eq('ini', iniHit, { hwid: 'ABC-123', os: 'Win10' });

  // 3. JSON path extraction
  const jsonHit = matchJson(
    { type: 'json', requires_keys: ['HWID'] },
    { paths: { hwid: '$.HWID', first: '$.Wallets[0].kind' } },
    { path: 'pc_info.json', text: '{"HWID":"X1","Wallets":[{"kind":"BTC"}]}' }
  );
  eq('json', jsonHit, { hwid: 'X1', first: 'BTC' });

  // 3b. YAML (safe load)
  const yamlHit = matchYaml(
    { type: 'yaml', requires_keys: ['Build'] },
    { paths: { build: '$.Build', hwid: '$.HWID' } },
    { path: 'info.yaml', text: 'Build: ACR-9.1\nHWID: Z2\n' }
  );
  eq('yaml', yamlHit, { build: 'ACR-9.1', hwid: 'Z2' });

  // 3c. RE2 matcher: named captures via WASM RE2
  const reHit = matchRegex(
    { type: 'regex', pattern: 'HWID:\\s*(?P<hwid>[A-Z0-9-]+)', multiline: true },
    { fields: ['hwid'] },
    { path: 'x.txt', text: 'noise\nHWID: ABC-999\n' }
  );
  eq('re2-hit', reHit, { hwid: 'ABC-999' });

  // 3d. RE2 ReDoS safety: a pattern that would hang native RegExp
  // for seconds must either return quickly or throw (we accept either).
  const t0 = Date.now();
  const evil = matchRegex(
    { type: 'regex', pattern: '^(a+)+$' },
    undefined,
    { path: 'x', text: 'a'.repeat(30) + '!' }
  );
  if (Date.now() - t0 > 500) throw new Error('RE2 ReDoS guard failed: took too long');
  if (evil !== null) throw new Error('RE2 match should have failed on bad input');

  // 4. glob
  if (!matchGlob('**/*.txt', 'a/b/c.txt')) throw new Error('glob should match');
  if (matchGlob('**/*.txt', 'a/b/c.json')) throw new Error('glob should not match');

  // 5. end-to-end: container + content via runRules
  /** @type {import('./types.js').RuleSpec[]} */
  const rules = [
    {
      id: 'lumma_folder', version: 1, layer: 'container', family: 'lumma', priority: 100,
      match: { type: 'folder', requires: ['System.txt'] }
    },
    {
      id: 'lumma_system_txt', version: 1, layer: 'content', family: 'lumma', priority: 100,
      path_glob: 'System.txt',
      match: { type: 'keyvalue', separator: ':', strip_whitespace: true, requires_keys: ['HWID'] },
      extract: { keys: { HWID: 'hwid', IP: 'ip', Country: 'country' } },
      normalize: [{ verb: 'uppercase', field: 'hwid' }, { verb: 'lowercase', field: 'country' }]
    }
  ];
  const folder = {
    rootName: 'victim-001',
    files: [{ path: 'System.txt', text: 'HWID: abc-123\nIP: 1.2.3.4\nCountry: US\n' }]
  };
  const r = runRules(rules, folder);
  eq('family', r.family, 'lumma');
  eq('merged', r.fields, { hwid: 'ABC-123', ip: '1.2.3.4', country: 'us' });

  return 'ok';
}
