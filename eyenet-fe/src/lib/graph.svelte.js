// Actor search state for the Graph page. GET /v1/graph/search is actors-only
// and `q` is REQUIRED (minLength 1) — there is no "browse all", so an empty
// box stays idle and fetches nothing. Svelte 5 runes in a module: one shared
// reactive object the page reads.
import { apiGet } from './api.js';

// ActorSummary → the row shape the DataTable consumes. id → actor_id (UUID),
// label → primary_handle. No kind/degree/tier: the API carries no such field.
function mapActor(a) {
  return {
    id: a.actor_id,
    handle: a.primary_handle,
    platforms: (a.platforms ?? []).join(', '),
    score: a.score == null ? '' : a.score.toFixed(2)
  };
}

// idle = box empty (no query yet). loading/error/results are the search states.
export const graphSearch = $state({ idle: true, loading: false, error: null, results: [] });

// Monotonic token so a slow in-flight request can't clobber a newer one.
let seq = 0;

export async function searchActors(q) {
  const term = q.trim();
  if (term === '') {
    graphSearch.idle = true;
    graphSearch.loading = false;
    graphSearch.error = null;
    graphSearch.results = [];
    return;
  }
  const mine = ++seq;
  graphSearch.idle = false;
  graphSearch.loading = true;
  graphSearch.error = null;
  try {
    const page = await apiGet(`/v1/graph/search?q=${encodeURIComponent(term)}&limit=50`, { auth: true });
    if (mine !== seq) return; // a newer search superseded this one
    graphSearch.results = page.items.map(mapActor);
    graphSearch.error = null;
  } catch (e) {
    if (mine !== seq) return;
    graphSearch.error = e.message ?? String(e);
    graphSearch.results = [];
  } finally {
    if (mine === seq) graphSearch.loading = false;
  }
}
