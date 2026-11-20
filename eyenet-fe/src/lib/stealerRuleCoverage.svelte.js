// Parse-misses dashboard state. Hits GET /v1/stealer/rule-coverage-gaps
// (read:stealer-gated) which answers "for each stealer family we classify,
// how many victims have NO fingerprint extraction?" Operator triage view
// for rule-authoring work: the biggest missing bucket is the highest-ROI
// target for the next userinfo_*_shape rule. Svelte 5 runes.
import { apiGet } from './api.js';

export const coverageCtx = $state({
  items: [],
  total_victims: 0,
  total_missing: 0,
  coverage_pct: 0,
  loading: false,
  error: null,
  denied: false,
  loaded: false,
});

export async function loadRuleCoverage() {
  coverageCtx.loading = true;
  coverageCtx.error = null;
  coverageCtx.denied = false;
  try {
    const r = await apiGet('/v1/stealer/rule-coverage-gaps', { auth: true });
    coverageCtx.items = r?.items ?? [];
    coverageCtx.total_victims = r?.total_victims ?? 0;
    coverageCtx.total_missing = r?.total_missing ?? 0;
    coverageCtx.coverage_pct = r?.coverage_pct ?? 0;
  } catch (e) {
    if (e.status === 403) coverageCtx.denied = true;
    else if (e.status === 503) coverageCtx.error = 'Corpus offline (the stealer pipeline is not running).';
    else coverageCtx.error = e.message ?? String(e);
    coverageCtx.items = [];
  } finally {
    coverageCtx.loading = false;
    coverageCtx.loaded = true;
  }
}
