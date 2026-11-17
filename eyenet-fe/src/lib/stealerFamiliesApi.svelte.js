// Thin client for /v1/stealer/families CRUD. Same fallback pattern as
// stealerRulesApi: reads fall back to the static /stealer-families.json
// export when the API isn't reachable; writes fail loudly.

import { apiGet, apiPost, apiPut, apiDelete } from '$lib/api.js';

const STATIC_LIST = '/stealer-families.json';

async function tryStatic() {
  try {
    const r = await fetch(STATIC_LIST);
    if (!r.ok) throw new Error(`static fetch ${r.status}`);
    return await r.json();
  } catch {
    return null;
  }
}

export async function listFamilies() {
  try {
    const r = await apiGet('/stealer/families', { auth: true });
    return r?.families ?? r ?? [];
  } catch {
    const s = await tryStatic();
    if (s) return s;
    throw new Error('families unavailable (API and static both failed)');
  }
}

export async function getFamily(slug) {
  try {
    return await apiGet(`/stealer/families/${encodeURIComponent(slug)}`, { auth: true });
  } catch {
    const s = await tryStatic();
    if (!s) throw new Error('getFamily: API and static both failed');
    const hit = s.find((f) => f.slug === slug);
    if (!hit) throw new Error(`family not found: ${slug}`);
    return hit;
  }
}

export async function createFamily(family) {
  return await apiPost('/stealer/families', family, { auth: true });
}

export async function updateFamily(slug, family) {
  return await apiPut(`/stealer/families/${encodeURIComponent(slug)}`, family, { auth: true });
}

export async function deleteFamily(slug) {
  return await apiDelete(`/stealer/families/${encodeURIComponent(slug)}`, { auth: true });
}
