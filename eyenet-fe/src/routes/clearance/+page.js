import { apiGet } from '$lib/api.js';

// Wire /clearance to the real API. One authenticated list call to
// /v1/clearance/grants. The API exposes `active` + timestamps, not a status
// enum, so the page derives active/expired/revoked client-side (see +page.svelte).
// A failing call renders as its own honest state rather than taking the page
// down: 401/403 = not authorized (stale token / missing read scope), other =
// unreachable.
export const load = async () => {
  const grants = await apiGet('/v1/clearance/grants?include_total=1', { auth: true })
    .then((page) => ({ page, status: 0 }))
    .catch((e) => ({ page: null, status: e.status ?? 0 }));
  return {
    items: grants.page?.items ?? null,
    total: grants.page?.estimated_total ?? null,
    nextCursor: grants.page?.next_cursor ?? null,
    grantsStatus: grants.status
  };
};
