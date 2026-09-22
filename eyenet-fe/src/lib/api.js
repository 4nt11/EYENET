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

// GET JSON. `accept` lists non-2xx statuses whose body is still meaningful
// (e.g. /v1/readyz returns 503 with a full ReadyStatus body when degraded).
export async function apiGet(path, { auth = false, accept = [] } = {}) {
  const headers = { accept: 'application/json' };
  if (auth) {
    const t = authToken();
    if (t) headers.authorization = `Bearer ${t}`;
  }
  const res = await fetch(`${BASE}${path}`, { headers });
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
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body)
  });
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
  const res = await fetch(`${BASE}${path}`, { method: 'DELETE', headers });
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
