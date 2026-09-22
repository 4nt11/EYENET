import { apiGet } from '$lib/api.js';

// Wire the graph stat tiles to GET /v1/graph/stats (auth, read:graph). Only the
// backable counters render: actors, personas, linkages-TOTAL (the sum of the
// LinkageStateCounts) and observations. A failure surfaces as data — the page
// renders its own state instead of the route erroring out.
export const load = async () => {
  try {
    return { stats: await apiGet('/v1/graph/stats', { auth: true }), statsStatus: 0 };
  } catch (e) {
    // 401/403 = no token / missing read:graph (expected), anything else = error.
    return { stats: null, statsStatus: e.status ?? 0 };
  }
};
