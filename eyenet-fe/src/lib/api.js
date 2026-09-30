// Thin fetch wrapper for the EYENET v1 API. No client lib — the platform's
// fetch does it. Base is same-origin by default (prod: UI + API behind one
// proxy); set VITE_EYENET_API to point dev at a separate origin (CORS-gated
// backend, EYENET_API_CORS_ORIGINS).
const BASE = import.meta.env.VITE_EYENET_API ?? '';

// Bearer for authenticated surfaces (e.g. /v1/system, read:metrics). Read from
// localStorage until a real login flow lands. localStorage throws in some
// privacy modes, so guard the exact failure.
export function authToken() {
  try {
    return localStorage.getItem('eyenet_token');
  } catch {
    return null;
  }
}

// Fired once whenever an *authenticated* request comes back 401 (token expired
// or revoked mid-session). The auth store registers a handler that drops the
// session; the reactive layout gate then falls back to the login form. api.js
// must NOT import the auth store (that would cycle — see auth.svelte.js), so
// the dependency is inverted through this setter.
let onUnauthorized = null;
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

// One fetch chokepoint so the 401 guard lives in a single place. `guard401` is
// true only when the caller sent auth AND did not explicitly accept a 401 as a
// meaningful response — so the login POST (auth:false) never triggers a
// redirect loop on a bad password.
async function doFetch(url, init, guard401) {
  const res = await fetch(url, init);
  if (guard401 && res.status === 401) onUnauthorized?.();
  return res;
}

// GET JSON. `accept` lists non-2xx statuses whose body is still meaningful
// (e.g. /v1/readyz returns 503 with a full ReadyStatus body when degraded).
export async function apiGet(path, { auth = false, accept = [] } = {}) {
  const headers = { accept: 'application/json' };
  if (auth) {
    const t = authToken();
    if (t) headers.authorization = `Bearer ${t}`;
  }
  const res = await doFetch(`${BASE}${path}`, { headers }, auth && !accept.includes(401));
  if (!res.ok && !accept.includes(res.status)) {
    const err = new Error(`${res.status} ${res.statusText}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

// POST JSON. `accept` lists non-2xx statuses to return rather than throw.
// On error, surfaces the problem+json `detail` when present.
export async function apiPost(path, body, { auth = false, accept = [], headers: extra = {} } = {}) {
  const headers = { accept: 'application/json', 'content-type': 'application/json', ...extra };
  if (auth) {
    const t = authToken();
    if (t) headers.authorization = `Bearer ${t}`;
  }
  const res = await doFetch(
    `${BASE}${path}`,
    { method: 'POST', headers, body: JSON.stringify(body) },
    auth && !accept.includes(401)
  );
  if (!res.ok && !accept.includes(res.status)) {
    let detail = `${res.status} ${res.statusText}`;
    const problem = await res.json().catch(() => null);
    if (problem?.detail) detail = problem.detail;
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

// POST multipart/form-data. Same auth + problem+json error contract as apiPost,
// but the body is a FormData and we DO NOT set content-type: the browser must
// set it (with the multipart boundary) itself. For file uploads (e.g. the
// identity .session upload at POST /v1/identities).
export async function apiPostForm(path, formData, { auth = false, accept = [], headers: extra = {} } = {}) {
  const headers = { accept: 'application/json', ...extra };
  if (auth) {
    const t = authToken();
    if (t) headers.authorization = `Bearer ${t}`;
  }
  const res = await doFetch(
    `${BASE}${path}`,
    { method: 'POST', headers, body: formData },
    auth && !accept.includes(401)
  );
  if (!res.ok && !accept.includes(res.status)) {
    let detail = `${res.status} ${res.statusText}`;
    const problem = await res.json().catch(() => null);
    if (problem?.detail) detail = problem.detail;
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

// PUT JSON. Same contract as apiPost (surfaces problem+json `detail`), for
// idempotent replace endpoints (e.g. PUT /v1/actors/{id}/assessment).
export async function apiPut(path, body, { auth = false, accept = [], headers: extra = {} } = {}) {
  const headers = { accept: 'application/json', 'content-type': 'application/json', ...extra };
  if (auth) {
    const t = authToken();
    if (t) headers.authorization = `Bearer ${t}`;
  }
  const res = await doFetch(
    `${BASE}${path}`,
    { method: 'PUT', headers, body: JSON.stringify(body) },
    auth && !accept.includes(401)
  );
  if (!res.ok && !accept.includes(res.status)) {
    let detail = `${res.status} ${res.statusText}`;
    const problem = await res.json().catch(() => null);
    if (problem?.detail) detail = problem.detail;
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

// PATCH JSON. Same contract as apiPut, for partial-update endpoints
// (e.g. PATCH /v1/collectors/{id}).
export async function apiPatch(path, body, { auth = false, accept = [], headers: extra = {} } = {}) {
  const headers = { accept: 'application/json', 'content-type': 'application/json', ...extra };
  if (auth) {
    const t = authToken();
    if (t) headers.authorization = `Bearer ${t}`;
  }
  const res = await doFetch(
    `${BASE}${path}`,
    { method: 'PATCH', headers, body: JSON.stringify(body) },
    auth && !accept.includes(401)
  );
  if (!res.ok && !accept.includes(res.status)) {
    let detail = `${res.status} ${res.statusText}`;
    const problem = await res.json().catch(() => null);
    if (problem?.detail) detail = problem.detail;
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

// DELETE. Surfaces the problem+json `detail` on error (e.g. a 409 when a
// collector isn't stopped). Returns null on 204.
export async function apiDelete(path, { auth = false, accept = [] } = {}) {
  const headers = { accept: 'application/json' };
  if (auth) {
    const t = authToken();
    if (t) headers.authorization = `Bearer ${t}`;
  }
  const res = await doFetch(`${BASE}${path}`, { method: 'DELETE', headers }, auth && !accept.includes(401));
  if (!res.ok && !accept.includes(res.status)) {
    let detail = `${res.status} ${res.statusText}`;
    const problem = await res.json().catch(() => null);
    if (problem?.detail) detail = problem.detail;
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return null;
  return res.json().catch(() => null);
}

// Format a byte count as GiB with one decimal, for host-stats tiles.
export function fmtGiB(bytes) {
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}
