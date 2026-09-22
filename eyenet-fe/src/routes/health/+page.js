import { apiGet } from '$lib/api.js';

// Wire the system page to the real API. Two calls:
//   /v1/readyz  — public, per-component up/down (200 ready, 503 degraded body)
//   /v1/system  — read:metrics, host CPU/RAM/disk/load
// Neither failing takes the page down: readiness renders without host stats,
// and an unreachable API renders as its own state.
export const load = async () => {
  const [ready, system] = await Promise.allSettled([
    apiGet('/v1/readyz', { accept: [503] }),
    apiGet('/v1/system', { auth: true })
  ]);
  return {
    ready: ready.status === 'fulfilled' ? ready.value : null,
    readyError: ready.status === 'rejected' ? String(ready.reason.message ?? ready.reason) : null,
    system: system.status === 'fulfilled' ? system.value : null,
    // 401/403 = not authorized (expected without a token), anything else = error.
    systemStatus: system.status === 'rejected' ? (system.reason.status ?? 0) : 0
  };
};
