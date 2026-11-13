// Proxy-pools workspace state (v1.2.0). GETs are proxy:read, writes are
// proxy:write, pool-reshape + bulk + reveal are proxy:admin.
//
// Pools are the top-level container; each pool has a list of proxies. The
// page loads the pool list, and selecting a pool lazy-loads its proxies so
// an operator with 50 pools and 10k proxies total does not ingest everything
// on entry.
import { apiDelete, apiGet, apiPatch, apiPost } from './api.js';

const shortTs = (ts) => (ts ? ts.replace('T', ' ').replace(/\..*$/, 'Z') : '');

function mapPool(p) {
  return {
    id: p.id,
    name: p.name,
    kindHint: p.kind_hint ?? '',
    description: p.description ?? '',
    created: shortTs(p.created_at)
  };
}

function mapProxy(p) {
  return {
    id: p.id,
    poolId: p.pool_id,
    kind: p.kind,
    host: p.host,
    port: p.port,
    hasSecret: p.has_secret,
    state: p.state,
    lastUsedAt: shortTs(p.last_used_at),
    lastHealthCheckAt: shortTs(p.last_health_check_at),
    lastError: p.last_error ?? '',
    source: p.source ?? '',
    boundIdentityId: p.bound_identity_id ?? null,
    notes: p.notes ?? '',
    created: shortTs(p.created_at)
  };
}

export const poolCtx = $state({ list: [], loaded: false, error: null });
export const proxyCtx = $state({
  byPool: {},     // { poolId: [proxy, ...] }
  loading: {},    // { poolId: bool }
  lastResult: null  // { inserted, skipped_duplicate, rejected } after a bulk op
});

// ----- pool CRUD --------------------------------------------------------

export async function loadPools() {
  try {
    const items = await apiGet('/v1/proxy-pools', { auth: true });
    poolCtx.list = items.map(mapPool);
    poolCtx.error = null;
  } catch (e) {
    poolCtx.error = e.message ?? String(e);
  } finally {
    poolCtx.loaded = true;
  }
}

export async function createPool({ name, kindHint, description }) {
  const body = {
    name,
    kind_hint: kindHint || null,
    description: description || null
  };
  const created = await apiPost('/v1/proxy-pools', body, { auth: true });
  poolCtx.list = [...poolCtx.list, mapPool(created)];
  return mapPool(created);
}

export async function updatePool(id, { name, kindHint, description }) {
  const body = {};
  if (name !== undefined) body.name = name;
  if (kindHint !== undefined) body.kind_hint = kindHint;
  if (description !== undefined) body.description = description;
  const updated = await apiPatch(`/v1/proxy-pools/${id}`, body, { auth: true });
  poolCtx.list = poolCtx.list.map((p) => (p.id === id ? mapPool(updated) : p));
  return mapPool(updated);
}

export async function deletePool(id) {
  await apiDelete(`/v1/proxy-pools/${id}`, { auth: true });
  poolCtx.list = poolCtx.list.filter((p) => p.id !== id);
  delete proxyCtx.byPool[id];
}

// ----- proxy CRUD -------------------------------------------------------

export async function loadProxies(poolId) {
  proxyCtx.loading[poolId] = true;
  try {
    const items = await apiGet(`/v1/proxy-pools/${poolId}/proxies`, { auth: true });
    proxyCtx.byPool[poolId] = items.map(mapProxy);
  } catch (e) {
    proxyCtx.byPool[poolId] = [];
    throw e;
  } finally {
    proxyCtx.loading[poolId] = false;
  }
}

export async function addProxy(poolId, { kind, host, port, secret, source, notes }) {
  const body = {
    kind,
    host,
    port: Number(port),
    secret: secret || null,
    source: source || null,
    notes: notes || null
  };
  const created = await apiPost(`/v1/proxy-pools/${poolId}/proxies`, body, { auth: true });
  const cur = proxyCtx.byPool[poolId] ?? [];
  proxyCtx.byPool[poolId] = [...cur, mapProxy(created)];
  return mapProxy(created);
}

export async function bulkAddProxies(poolId, { lines, defaultKind, source }) {
  const body = {
    lines,
    default_kind: defaultKind || null,
    source: source || null
  };
  const result = await apiPost(`/v1/proxy-pools/${poolId}/proxies/bulk`, body, { auth: true });
  proxyCtx.lastResult = result;
  // Refresh the list so the operator sees what landed.
  await loadProxies(poolId);
  return result;
}

export async function updateProxyState(proxyId, state, reason) {
  const body = { state, reason: reason || null };
  const updated = await apiPost(`/v1/proxies/${proxyId}/state`, body, { auth: true });
  const mapped = mapProxy(updated);
  // Update in whichever pool list has it.
  for (const pid of Object.keys(proxyCtx.byPool)) {
    const idx = proxyCtx.byPool[pid].findIndex((p) => p.id === proxyId);
    if (idx >= 0) {
      const next = [...proxyCtx.byPool[pid]];
      next[idx] = mapped;
      proxyCtx.byPool[pid] = next;
      break;
    }
  }
  return mapped;
}

export async function deleteProxy(proxyId, poolId) {
  await apiDelete(`/v1/proxies/${proxyId}`, { auth: true });
  if (proxyCtx.byPool[poolId]) {
    proxyCtx.byPool[poolId] = proxyCtx.byPool[poolId].filter((p) => p.id !== proxyId);
  }
}

// ----- credential reveal (proxy:admin) ----------------------------------

export async function revealSecret(proxyId) {
  const detail = await apiGet(`/v1/proxies/${proxyId}?reveal=true`, { auth: true });
  return detail.secret ?? null;
}

// ----- identity<->pool binding -----------------------------------------

export async function bindIdentityToPool(identityId, { poolId, sticky }) {
  const body = {
    pool_id: poolId ?? null,
    sticky: sticky === undefined ? null : sticky
  };
  return apiPatch(`/v1/identities/${identityId}/proxy`, body, { auth: true });
}
