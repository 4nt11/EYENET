// Thin client for /v1/stealer/rules CRUD. Hits the real API in prod;
// falls back to /stealer-rules.json (the static export) for list/get
// so the FE still works pre-deploy or when run against an unauthenticated
// dev build. The write operations have no fallback; they fail loudly.

import { apiGet, apiPost, apiPut, apiDelete } from '$lib/api.js';

const STATIC_LIST = '/stealer-rules.json';

async function tryStatic() {
  try {
    const r = await fetch(STATIC_LIST);
    if (!r.ok) throw new Error(`static fetch ${r.status}`);
    return await r.json();
  } catch {
    return null;
  }
}

export async function listRules() {
  try {
    const r = await apiGet('/v1/stealer/rules', { auth: true });
    return r?.rules ?? r ?? [];
  } catch {
    const s = await tryStatic();
    if (s) return s;
    throw new Error('rules unavailable (API and static both failed)');
  }
}

export async function getRule(id) {
  try {
    return await apiGet(`/v1/stealer/rules/${encodeURIComponent(id)}`, { auth: true });
  } catch {
    const s = await tryStatic();
    if (!s) throw new Error('getRule: API and static both failed');
    const hit = s.find((r) => r.id === id);
    if (!hit) throw new Error(`rule not found: ${id}`);
    return hit;
  }
}

export async function createRule(rule) {
  return await apiPost('/v1/stealer/rules', rule, { auth: true });
}

export async function updateRule(id, rule) {
  return await apiPut(`/v1/stealer/rules/${encodeURIComponent(id)}`, rule, { auth: true });
}

export async function deleteRule(id) {
  return await apiDelete(`/v1/stealer/rules/${encodeURIComponent(id)}`, { auth: true });
}

// Dry-run validation: the server returns {valid: bool, error: string|null}
// WITHOUT writing anything. Powers the "Validate" button in the rule editor.
export async function validateRule(rule) {
  return await apiPost('/v1/stealer/rules/validate', rule, { auth: true });
}
