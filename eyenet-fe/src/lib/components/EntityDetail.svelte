<script>
  import Badge from './Badge.svelte';

  // Shared detail flyout for a selected search hit — used by BOTH the table rows
  // and the graph nodes so the two lenses inspect an entity identically. `entity`
  // carries { entityType, id, title, subtitle?, status?, sourceId }. `fields` is
  // the optional per-entity bag (table rows have it; graph nodes don't) rendered
  // as a key/value list. `sourceName` resolves the raw source id to its human
  // label. `onClose` clears the parent's selection.
  let { entity, sourceName = (x) => x ?? '', fields = null, onClose } = $props();

  const cap = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);

  // Best-effort deep-link map: not every entity_type has a detail screen.
  const ROUTE = {
    actor: (r) => `/actors?id=${r.id}`,
    persona: (r) => `/personas?id=${r.id}`,
    case: (r) => `/cases?id=${r.id}`,
    group: (r) => `/monitored-groups?id=${r.id}`,
    thread: (r) => `/monitored-groups?id=${r.id}`
  };
  const ROUTE_LABEL = { actor: 'Actors', persona: 'Personas', case: 'Cases', group: 'Monitored groups', thread: 'Monitored groups' };
  const HAS_HANDLE = new Set(['message', 'actor', 'thread', 'mention']);

  const fmtVal = (v) => (Array.isArray(v) ? v.join(', ') : typeof v === 'object' ? JSON.stringify(v) : String(v));
  let fieldRows = $derived(
    fields ? Object.entries(fields).filter(([, v]) => v != null && v !== '') : []
  );
</script>

<div class="detail">
  <div class="detail-head">
    <Badge tone="high">{cap(entity.entityType)}</Badge>
    <button class="detail-close" onclick={onClose} aria-label="Close detail">×</button>
  </div>
  <div class="dtitle">{entity.title || '—'}</div>

  {#if entity.subtitle}
    <div class="dfield">
      <span class="dk">{HAS_HANDLE.has(entity.entityType) ? 'Author / handle' : 'Subtitle'}</span>
      <span class="dv">{entity.subtitle}</span>
    </div>
  {/if}
  {#if entity.status}
    <div class="dfield"><span class="dk">Status</span><span class="dv mono">{entity.status}</span></div>
  {/if}
  <div class="dfield"><span class="dk">Source</span><span class="dv mono" title={entity.sourceId ?? ''}>{sourceName(entity.sourceId) || '—'}</span></div>
  <div class="dfield"><span class="dk">Entity id</span><span class="dv mono" title={entity.id}>{entity.id}</span></div>

  {#if fieldRows.length}
    <div class="fgrid">
      {#each fieldRows as [k, v]}
        <div class="dfield"><span class="dk">{k}</span><span class="dv">{fmtVal(v)}</span></div>
      {/each}
    </div>
  {/if}

  {#if ROUTE[entity.entityType]}
    <a class="dopen" href={ROUTE[entity.entityType](entity)}>Open in {ROUTE_LABEL[entity.entityType]} →</a>
  {:else}
    <p class="dnote">No dedicated detail screen for this entity type.</p>
  {/if}
</div>

<style>
  .detail { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 14px; display: flex; flex-direction: column; gap: 10px; }
  .detail-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .detail-close { appearance: none; background: transparent; border: none; color: var(--text-faint); font-size: var(--fs-18); line-height: 1; cursor: pointer; padding: 0 4px; }
  .detail-close:hover { color: var(--accent-text); }
  .dtitle { font-family: var(--font-sans); font-size: var(--fs-14); font-weight: var(--fw-semibold); color: var(--text); line-height: var(--lh-tight); word-break: break-word; }
  .dfield { display: flex; flex-direction: column; gap: 2px; }
  .dk { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .dv { font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); word-break: break-word; white-space: pre-wrap; }
  .dv.mono { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); }
  .fgrid { display: flex; flex-direction: column; gap: 8px; border-top: 1px solid var(--border); padding-top: 10px; }
  .dopen { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); text-decoration: none; margin-top: 2px; }
  .dopen:hover { color: var(--link-hover); text-decoration: underline; }
  .dnote { margin: 2px 0 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); }
</style>
