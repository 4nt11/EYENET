import { apiGet } from '$lib/api.js';

// Wire the graph stat tiles to GET /v1/graph/stats (auth, read:graph). Only the
// backable counters render: actors, personas, linkages-TOTAL (the sum of the
// LinkageStateCounts) and observations. A failure surfaces as data — the page
// renders its own state instead of the route erroring out.
export const load = async () => {
  const stats = await apiGet('/v1/graph/stats', { auth: true }).then(
    (v) => ({ status: 'fulfilled', value: v }),
    (e) => ({ status: 'rejected', reason: e })
  );
  return {
    stats: stats.status === 'fulfilled' ? stats.value : null,
    // 401/403 = no token / missing read:graph (expected), anything else = error.
    statsStatus: stats.status === 'rejected' ? (stats.reason.status ?? 0) : 0
  };
};
