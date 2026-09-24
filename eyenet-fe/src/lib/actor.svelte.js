// Actors workspace state. List from GET /v1/actors; selecting one fetches the
// dossier: GET /v1/actors/{id} (+ /observations, /timeline, /neighbors), the
// calibration baseline (cached), and each linked neighbor's linkage detail for
// the verifier composite. The BEHAVE panel is built from real observations
// grouped by primitive namespace. Assessment is a sync write (write:actors).
import { apiGet, apiPost, apiPut } from './api.js';

const short = (id) => (id ? id.slice(0, 8) : '');
const shortTs = (ts) => (ts ? ts.replace('T', ' ').replace(/\..*$/, 'Z') : '·');
const shortHash = (h) => (h && h.length > 12 ? `${h.slice(0, 8)}…` : (h ?? ''));

function mapActor(a) {
  return {
    id: a.actor_id,
    handle: a.primary_handle,
    platforms: a.platforms ?? [],
    isBot: !!a.is_bot,
    messageCount: a.message_count ?? 0,
    observationCount: a.observation_count ?? 0
  };
}

export const actorCtx = $state({
  list: [],
  loaded: false,
  error: null,
  nextCursor: null,
  loadingMore: false,
  total: null // estimated_total for the current filter set
});

// List filters + sort. isBot: null=all, true=bots, false=users. Message/observation
// filters are [min, max] ranges; a thumb at 0 (min) or the roster ceiling (max)
// means that side is unset and isn't sent.
export const actorFilters = $state({
  sort: 'recent', // recent | messages | observations | handle
  isBot: null,
  groupId: '',
  minMessages: 0,
  maxMessages: 0,
  minObservations: 0,
  maxObservations: 0
});
export const actorBounds = $state({ maxMessages: 0, maxObservations: 0 });
export const groupOptions = $state({ list: [] });

const _PAGE = 200;

function _query(extra = '') {
  const p = new URLSearchParams();
  p.set('limit', String(_PAGE));
  p.set('include_total', '1');
  p.set('sort', actorFilters.sort);
  if (actorFilters.isBot !== null) p.set('is_bot', actorFilters.isBot ? 'true' : 'false');
  if (actorFilters.groupId) p.set('group_id', actorFilters.groupId);
  if (actorFilters.minMessages > 0) p.set('min_messages', String(actorFilters.minMessages));
  if (actorBounds.maxMessages && actorFilters.maxMessages < actorBounds.maxMessages)
    p.set('max_messages', String(actorFilters.maxMessages));
  if (actorFilters.minObservations > 0) p.set('min_observations', String(actorFilters.minObservations));
  if (actorBounds.maxObservations && actorFilters.maxObservations < actorBounds.maxObservations)
    p.set('max_observations', String(actorFilters.maxObservations));
  return `/v1/actors?${p.toString()}${extra}`;
}

// Roster-wide slider ceilings; fetched once, sets the initial max thumbs to full.
export async function loadActorBounds() {
  try {
    const s = await apiGet('/v1/actors/stats', { auth: true });
    actorBounds.maxMessages = s.max_messages ?? 0;
    actorBounds.maxObservations = s.max_observations ?? 0;
    actorFilters.maxMessages = actorBounds.maxMessages;
    actorFilters.maxObservations = actorBounds.maxObservations;
  } catch {
    /* leave at 0 — sliders render inert until bounds load */
  }
}

export async function loadActors() {
  try {
    const page = await apiGet(_query(), { auth: true });
    actorCtx.list = page.items.map(mapActor);
    actorCtx.nextCursor = page.next_cursor ?? null;
    actorCtx.total = page.estimated_total ?? null;
    actorCtx.error = null;
  } catch (e) {
    actorCtx.error = e.message ?? String(e);
    actorCtx.list = [];
    actorCtx.nextCursor = null;
  } finally {
    actorCtx.loaded = true;
  }
}

// Append the next cursor page (the "Load more" action). Cursor pagination, so we
// pass the server's opaque next_cursor rather than an offset.
export async function loadMoreActors() {
  if (!actorCtx.nextCursor || actorCtx.loadingMore) return;
  actorCtx.loadingMore = true;
  try {
    const page = await apiGet(_query(`&cursor=${encodeURIComponent(actorCtx.nextCursor)}`), { auth: true });
    actorCtx.list = [...actorCtx.list, ...page.items.map(mapActor)];
    actorCtx.nextCursor = page.next_cursor ?? null;
  } catch (e) {
    actorCtx.error = e.message ?? String(e);
  } finally {
    actorCtx.loadingMore = false;
  }
}

// Group filter options: only monitored groups (those with a real group_id).
export async function loadGroupOptions() {
  try {
    const page = await apiGet('/v1/groups?limit=200', { auth: true });
    groupOptions.list = (page.items ?? [])
      .filter((g) => g.group_id)
      .map((g) => ({ id: g.group_id, label: g.title || g.platform_groupid }));
  } catch {
    groupOptions.list = [];
  }
}

// Debounced reload when a filter changes (numeric inputs fire per keystroke).
let _ftimer;
export function applyFilters() {
  clearTimeout(_ftimer);
  _ftimer = setTimeout(loadActors, 150);
}

// Calibration is language-level config, fetched once and cached.
let _calibration = null;
async function getCalibration() {
  if (_calibration) return _calibration;
  try {
    _calibration = await apiGet('/v1/calibration', { auth: true });
  } catch {
    _calibration = { composite_floor: null, comparators: [], verifiers: [] };
  }
  return _calibration;
}

export const actorView = $state({
  id: null,
  detail: null, // {handle, actorId, platforms, firstSeen, lastSeen, aliasCount, observationCount, personaId, score}
  aliases: [],
  assessment: '',
  behave: null,
  observations: [],
  neighbors: [],
  relationships: { outbound: [], inbound: [] },
  timeline: [],
  timelineKind: 'all', // 'all' | 'message' | 'observation'
  timelineLoading: false,
  loading: false,
  error: null,
  submitting: false,
  submitMsg: null,
  rebuilding: false,
  rebuildMsg: null
});

const _shortRel = (r) => ({
  actorId: r.actor_id,
  handle: r.handle || r.actor_id.slice(0, 8),
  displayName: r.display_name || '',
  kind: r.kind,
  count: r.count,
  lastSeen: shortTs(r.last_seen)
});

function _timelineUrl(id, kind) {
  const k = kind && kind !== 'all' ? `&kind=${kind}` : '';
  return `/v1/actors/${id}/timeline?limit=50${k}`;
}

const _mapTimeline = (items) =>
  (items ?? []).map((t) => ({ ts: shortTs(t.ts), kind: t.kind, summary: t.summary ?? '' }));

// Round to at most 4 decimals, dropping trailing zeros (integers stay integers).
// Keeps the value column uniform + right-aligned instead of a 16-digit float
// overflowing its width.
function fmtNum(n) {
  if (n == null) return '';
  return Number.isInteger(n) ? String(n) : String(Math.round(n * 1e4) / 1e4);
}

// A hash-kind value that is actually a timestamp (first_seen_ts / last_seen_ts)
// renders as a clean YYYY-MM-DD date, not a mid-string ellipsis. Real hashes
// (punctuation_style etc.) still get the short-hash treatment.
function fmtHash(v) {
  if (!v) return '';
  const iso = /^(\d{4}-\d{2}-\d{2})/.exec(v);
  return iso ? iso[1] : shortHash(v);
}

// Which value_* field carries an observation's payload, by value_kind.
function obsValue(o) {
  switch (o.value_kind) {
    case 'numeric': return fmtNum(o.score);
    case 'hash': return fmtHash(o.value_hash);
    case 'enum_str': return o.value_enum ?? '';
    case 'array_str': return (o.value_array ?? []).join(', ');
    case 'array_numeric': return (o.value_array_numeric ?? []).map((n) => n.toFixed(2)).join(', ');
    default: return fmtNum(o.score);
  }
}

const _BUCKET = { meta: 'activity', lexical: 'lexical', stylometric: 'stylometric' };

// One BEHAVE row per primitive: a primitive is re-observed on every message, so
// the raw stream repeats the same ~8 primitives dozens of times. Collapse to the
// latest value per primitive (by ts) — the "current reading" that updates as new
// observations land, instead of a wall of duplicates.
function _latestPerPrimitive(observations) {
  const latest = new Map();
  for (const o of observations) {
    const prev = latest.get(o.kind);
    if (!prev || String(o.ts ?? '') >= String(prev.ts ?? '')) latest.set(o.kind, o);
  }
  return [...latest.values()];
}

function buildBehave(observations, calibration, verifier) {
  const activity = [];
  const lexical = [];
  const stylometric = [];
  for (const o of _latestPerPrimitive(observations)) {
    const row = { primitive: o.kind, label: o.primitive ?? o.kind, value: obsValue(o), kind: o.value_kind ?? '' };
    const bucket = _BUCKET[o.primitive_namespace] ?? 'lexical';
    if (bucket === 'activity') activity.push(row);
    else if (bucket === 'stylometric') stylometric.push(row);
    else lexical.push(row);
  }
  // Stable, readable order within each bucket.
  const byLabel = (a, b) => a.label.localeCompare(b.label);
  activity.sort(byLabel);
  lexical.sort(byLabel);
  stylometric.sort(byLabel);
  // Comparators are language-level calibration; with no per-actor pairwise
  // distance we render enabled/disabled status + the threshold (no result).
  const comparators = (calibration.comparators ?? []).map((c) => {
    // Disabled iff any per-language override is null (e.g. Spanish simhash).
    const disabledLangs = Object.entries(c.per_lang ?? {})
      .filter(([, v]) => v === null)
      .map(([k]) => k);
    if (disabledLangs.length) {
      return { name: c.name, status: 'disabled', distance: null, threshold: null,
        reason: `disabled for ${disabledLangs.join(', ')}` };
    }
    return { name: c.name, status: 'enabled', distance: null, threshold: c.language_blind_threshold,
      reason: `threshold ${c.language_blind_threshold} · no pairwise result on this actor` };
  });
  return {
    language: 'und',
    anchors: stylometric.length,
    dialect_region: '',
    activity,
    lexical,
    stylometric,
    comparators,
    verifier: verifier ?? { state: 'skipped', composite: null, floor: null, results: [] }
  };
}

// Fetch each linked neighbor's linkage detail; return the highest-composite
// verifier result (the actor's strongest verified linkage), mapped to the
// BehavePanel shape.
async function bestVerifier(neighbors) {
  const linkageIds = neighbors
    .filter((n) => n.edge_type === 'linked_to' && n.attrs?.linkage_id)
    .map((n) => n.attrs.linkage_id);
  if (!linkageIds.length) return null;
  const details = await Promise.all(
    linkageIds.map((lid) => apiGet(`/v1/linkages/${lid}`, { auth: true }).catch(() => null))
  );
  let best = null;
  for (const d of details) {
    if (d?.verifier && (best == null || d.verifier.composite > best.composite)) best = d.verifier;
  }
  if (!best) return null;
  return {
    state: best.state,
    composite: best.composite,
    floor: best.floor,
    results: (best.results ?? []).map((r) => ({
      verifier: r.method, score: r.score, confidence: r.confidence,
      skipped: r.skipped, detail: r.detail ?? ''
    }))
  };
}

let detailSeq = 0;

export async function loadActorDetail(id) {
  const mine = ++detailSeq;
  actorView.loading = true;
  actorView.id = id;
  actorView.detail = null;
  actorView.aliases = [];
  actorView.assessment = '';
  actorView.behave = null;
  actorView.observations = [];
  actorView.neighbors = [];
  actorView.relationships = { outbound: [], inbound: [] };
  actorView.timeline = [];
  actorView.timelineKind = 'all';
  actorView.error = null;
  actorView.submitMsg = null;
  try {
    const [detail, obsPage, tlPage, neighborList, relList, calibration] = await Promise.all([
      apiGet(`/v1/actors/${id}`, { auth: true }),
      apiGet(`/v1/actors/${id}/observations?limit=200`, { auth: true }),
      apiGet(_timelineUrl(id, 'all'), { auth: true }),
      apiGet(`/v1/actors/${id}/neighbors?limit=50`, { auth: true }),
      apiGet(`/v1/actors/${id}/relationships?limit=50`, { auth: true }),
      getCalibration()
    ]);
    if (mine !== detailSeq) return;
    const observations = obsPage.items ?? [];
    const neighbors = neighborList.items ?? [];
    const verifier = await bestVerifier(neighbors);
    if (mine !== detailSeq) return;

    actorView.detail = {
      handle: detail.primary_handle,
      actorId: detail.actor_id,
      platforms: detail.platforms ?? [],
      firstSeen: shortTs(detail.first_seen),
      lastSeen: shortTs(detail.last_seen),
      aliasCount: detail.alias_count ?? 0,
      observationCount: detail.observation_count ?? 0,
      personaId: detail.persona_id ?? null,
      score: detail.score ?? null,
      isBot: !!detail.is_bot
    };
    actorView.aliases = (detail.aliases ?? []).map((al) => `${al.value} (${al.kind})`);
    actorView.assessment = detail.assessment ?? '';
    actorView.observations = observations.map((o) => ({
      observation_id: o.observation_id,
      kind: o.kind,
      ts: shortTs(o.ts),
      value: obsValue(o),
      sensitivity: o.sensitivity
    }));
    actorView.neighbors = neighbors.map((n) =>
      n.edge_type === 'belongs_to_persona'
        ? { edge_type: 'belongs_to_persona', target_id: short(n.target_id), since: shortTs(n.attrs?.since) }
        : {
            edge_type: 'linked_to',
            target_id: short(n.target_id),
            state: n.attrs?.state,
            method: n.attrs?.method,
            score: n.attrs?.score
          }
    );
    actorView.relationships = {
      outbound: (relList.outbound ?? []).map(_shortRel),
      inbound: (relList.inbound ?? []).map(_shortRel)
    };
    actorView.timeline = _mapTimeline(tlPage.items);
    actorView.behave = buildBehave(observations, calibration, verifier);
    actorView.error = null;
  } catch (e) {
    if (mine !== detailSeq) return;
    actorView.error = e.message ?? String(e);
  } finally {
    if (mine === detailSeq) actorView.loading = false;
  }
}

// Switch the timeline stream filter and refetch just that panel.
export async function setTimelineKind(id, kind) {
  actorView.timelineKind = kind;
  actorView.timelineLoading = true;
  try {
    const page = await apiGet(_timelineUrl(id, kind), { auth: true });
    actorView.timeline = _mapTimeline(page.items);
  } catch (e) {
    actorView.error = e.message ?? String(e);
  } finally {
    actorView.timelineLoading = false;
  }
}

// Operator-triggered rebuild of the actor-to-actor relation graph, then reload
// the current dossier so the Relationships panel reflects the fresh pass.
export async function rebuildRelations(id) {
  actorView.rebuilding = true;
  actorView.rebuildMsg = null;
  try {
    const res = await apiPost('/v1/relations/rebuild', {}, { auth: true, accept: [202] });
    actorView.rebuildMsg = `Rebuilt: ${res.edges} edges.`;
    if (id) await loadActorDetail(id);
    return true;
  } catch (e) {
    actorView.rebuildMsg = `Failed: ${e.message ?? e}`;
    return false;
  } finally {
    actorView.rebuilding = false;
  }
}

// Sync write (write:actors); durable on return, so reload the detail after.
export async function saveAssessment(id, text, reason) {
  actorView.submitting = true;
  actorView.submitMsg = null;
  try {
    await apiPut(
      `/v1/actors/${id}/assessment`,
      { assessment: text, reason },
      { auth: true, headers: { 'Idempotency-Key': crypto.randomUUID() } }
    );
    actorView.submitMsg = 'Assessment saved.';
    actorView.assessment = text;
    return true;
  } catch (e) {
    actorView.submitMsg = `Failed: ${e.message ?? e}`;
    return false;
  } finally {
    actorView.submitting = false;
  }
}
