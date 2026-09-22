// Route smoke test. `bun run build` only prerenders the fallback shell (ssr is
// off), so a runtime fault in a page's <script> — a TDZ, an undefined access —
// compiles clean and only explodes in a browser. This loads every route in a
// real (headless) browser and FAILS on any uncaught page error or console
// error. It mocks the API (no live backend needed) and seeds a token so the
// auth gate lets the routes render.
//
//   run a server first, then:  EYENET_SMOKE_URL=http://localhost:5173 node smoke.mjs
//   default URL is http://localhost:5173
import { chromium } from 'playwright';
import { readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const BASE = process.env.EYENET_SMOKE_URL ?? 'http://localhost:5173';

// Discover routes from the filesystem: any dir with a +page.svelte. Skip
// dynamic [param] segments (no value to smoke) and () layout groups.
function discoverRoutes(dir = 'src/routes', prefix = '') {
  const out = [];
  if (existsSync(join(dir, '+page.svelte')) && prefix !== '') out.push(prefix);
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name.includes('[')) continue;
    const seg = entry.name.startsWith('(') ? '' : `/${entry.name}`;
    out.push(...discoverRoutes(join(dir, entry.name), prefix + seg));
  }
  return out;
}

// Minimal valid response per endpoint so pages render their happy path without
// throwing on a missing required field.
function mockBody(path) {
  const page = { items: [], next_cursor: null, estimated_total: 0 };
  if (path.endsWith('/v1/auth/me'))
    return { user_id: '00000000-0000-7000-8000-000000000001', username: 'smoke', role: 'admin',
      scopes: ['read:graph', 'read:metrics', 'read:sources', 'read:cases', 'read:audit',
        'read:collectors', 'read:candidates', 'read:actors', 'read:personas', 'read:linkages'] };
  if (path.endsWith('/v1/readyz')) return { status: 'ready', components: { storage: 'up', bus: 'up', auth_keys: 'up' } };
  if (path.endsWith('/v1/system'))
    return { cpu_percent: 1, mem: { used: 1, total: 2, percent: 50 },
      disk: { data: { used: 1, free: 1, total: 2 }, root: { used: 1, free: 1, total: 2 } },
      load1: 0.1, uptime_seconds: 100, version: '0.0.0',
      components: { storage: 'sqlite', bus: 'memory', auth_keys: '1 verifying key' } };
  if (path.endsWith('/v1/graph/stats'))
    return { actors: 0, personas: 0, linkages: { proposed: 0, suspected: 0, confirmed: 0, rejected: 0 }, observations: 0, computed_at: '2026-01-01T00:00:00Z' };
  if (path.endsWith('/v1/audit/verify')) return { verified: true, rows_checked: 0, first_break: null };
  if (path.includes('/v1/sources/') && !path.endsWith('/v1/sources'))
    return { source_id: 'x', kind: 'telegram', display_name: 'x', active_domain_count: 0, created_at: '2026-01-01T00:00:00Z', domains: [], resolved_artifact_count: 0 };
  return page; // every list endpoint
}

const routes = discoverRoutes();
const browser = await chromium.launch();
const ctx = await browser.newContext({ ignoreHTTPSErrors: true });

// Intercept the API before any request leaves the page; seed a token so the
// layout's auth gate resolves and renders the routes.
await ctx.route('**/v1/**', (route) =>
  route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockBody(new URL(route.request().url()).pathname)) })
);
await ctx.addInitScript(() => {
  try {
    localStorage.setItem('eyenet_token', 'smoke');
    localStorage.setItem('eyenet_refresh', 'smoke');
  } catch {}
});

const failures = [];
for (const route of routes) {
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  try {
    await page.goto(BASE + route, { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(300); // let effects/onMount settle
  } catch (e) {
    errors.push(`navigation failed: ${e.message}`);
  }
  await page.close();
  if (errors.length) {
    failures.push({ route, errors });
    console.log(`✗ ${route}`);
    for (const e of errors) console.log(`    ${e.split('\n')[0]}`);
  } else {
    console.log(`✓ ${route}`);
  }
}

await browser.close();
console.log(`\n${routes.length - failures.length}/${routes.length} routes clean`);
if (failures.length) {
  console.error(`SMOKE FAILED: ${failures.length} route(s) threw at runtime.`);
  process.exit(1);
}
