// Reactive auth session. One shared $state object every component reads; the
// layout gate renders the app only when `token` is present and validated.
// Tokens live in localStorage so a refresh keeps the session; the store is the
// in-memory mirror. api.js reads the same localStorage key (no import cycle).
import { apiGet, apiPost } from './api.js';

const TOKEN_KEY = 'eyenet_token';
const REFRESH_KEY = 'eyenet_refresh';

function read(k) {
  try {
    return localStorage.getItem(k);
  } catch {
    return null;
  }
}
function write(k, v) {
  try {
    if (v == null) localStorage.removeItem(k);
    else localStorage.setItem(k, v);
  } catch {
    // private mode / storage disabled — session just won't survive reload.
  }
}

export const auth = $state({
  token: read(TOKEN_KEY),
  refresh: read(REFRESH_KEY),
  user: null, // UserMe {user_id, username, role, scopes} once loaded
  ready: false // true after the first loadMe() settles
});

function setTokens(pair) {
  auth.token = pair.access_token;
  auth.refresh = pair.refresh_token;
  write(TOKEN_KEY, pair.access_token);
  write(REFRESH_KEY, pair.refresh_token);
}

function clearSession() {
  auth.token = null;
  auth.refresh = null;
  auth.user = null;
  write(TOKEN_KEY, null);
  write(REFRESH_KEY, null);
}

// Returns {mfaChallengeId} when the account has MFA enrolled (caller then
// collects a code and calls verifyMfa), or {ok:true} when logged straight in.
export async function login(username, password) {
  const res = await apiPost('/v1/auth/login', { username, password });
  if (res.kind === 'mfa_required' || res.mfa_required) {
    return { mfaChallengeId: res.mfa_challenge_id };
  }
  setTokens(res);
  await loadMe();
  return { ok: true };
}

export async function verifyMfa(challengeId, code) {
  const pair = await apiPost('/v1/auth/login/verify', {
    mfa_challenge_id: challengeId,
    code
  });
  setTokens(pair);
  await loadMe();
}

// Validate the stored token by resolving /v1/auth/me. A 401 means the token is
// stale/expired — drop it so the gate falls back to the login form.
export async function loadMe() {
  if (!auth.token) {
    auth.user = null;
    auth.ready = true;
    return;
  }
  try {
    auth.user = await apiGet('/v1/auth/me', { auth: true });
  } catch (e) {
    if (e.status === 401) clearSession();
  } finally {
    auth.ready = true;
  }
}

export async function logout() {
  try {
    // Server-side revoke (denylist access jti + refresh) needs the bearer.
    await apiPost('/v1/auth/logout', { refresh_token: auth.refresh }, { auth: true });
  } finally {
    // Local logout must succeed even if the server call fails (offline).
    clearSession();
  }
}
