<script>
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { boardOf, prepare, onGuardedClick } from '$lib/linkguard.js';
  import { apiGet, apiPost } from '$lib/api.js';
  import { incidentLabelName, incidentTone, INCIDENT_LABELS } from '$lib/data.js';
  import { relabelIncident, incidentEdit } from '$lib/incident.svelte.js';
  import Badge from '$lib/components/Badge.svelte';
  import CaseAddModal from '$lib/components/CaseAddModal.svelte';

  // Message view for any group: a forum thread OR a chat/channel/room. Posts
  // render their evidence-faithful body_html (SANITIZED — this is threat-actor
  // HTML; raw {@html} would XSS the console); chat messages with no html fall
  // back to escaped body text. If any post is [hide]-gated, the operator can
  // enqueue a reply-to-unlock (posted by the collector under throttle).
  let msgs = $state([]);
  let caseModalPost = $state(null); // {id, actor_id, author, threadTitle} or null
  let error = $state(null);
  let loaded = $state(false);
  let search = $state(''); // in-context body search, scoped to THIS group (thread/channel)
  let total = $state(null); // estimated_total for the current (filtered) view
  let searchTimer;
  let replyText = $state('');
  let replyMsg = $state(null);
  let submitting = $state(false);
  let backfillMsg = $state(null);
  let backfilling = $state(false);

  const gated = $derived(msgs.some((m) => m.reply_gated));
  // Forum posts carry body_html; chats don't. Deep backfill only applies to forums.
  const isForum = $derived(msgs.some((m) => m.body_html != null));

  onMount(load);

  async function load() {
    loaded = false;
    error = null;
    const params = new URLSearchParams({ limit: '500', include_total: '1' });
    if (search.trim()) params.set('q', search.trim()); // scoped to this group only
    try {
      const p = await apiGet(`/v1/groups/${$page.params.id}/messages?${params}`, { auth: true });
      msgs = p.items ?? [];
      total = p.estimated_total ?? null;
    } catch (e) {
      error = e.message;
    }
    loaded = true;
  }

  // Debounce keystrokes: one request 250ms after the operator stops typing.
  function onSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(load, 250);
  }

  const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : '');

  // Per-post relabel editor (same ground-truth flow as the incidents page). Only one
  // post's editor is open at a time (editId).
  const REASON_PRESETS = ['False positive', 'Incorrectly tagged', 'Missing label', 'Partially correct'];
  let editId = $state(null);
  let draft = $state(new Set());
  let reason = $state('');
  let customReason = $state(false);
  const canSave = $derived(reason.trim().length > 0 && !incidentEdit.submitting);

  function startEdit(m) {
    editId = m.id;
    draft = new Set(m.corrected_labels ?? m.incident_labels ?? []);
    reason = '';
    customReason = false;
  }
  function toggleLabel(l) {
    const n = new Set(draft);
    n.has(l) ? n.delete(l) : n.add(l);
    draft = n;
  }
  async function saveLabels(m) {
    const labels = INCIDENT_LABELS.filter((l) => draft.has(l));
    const ok = await relabelIncident(m.id, labels, reason.trim());
    if (ok) {
      m.corrected_labels = labels; // reflect the correction inline
      editId = null;
    }
  }

  // Link defang + triple-click-to-open guard live in $lib/linkguard.js (shared
  // with the category reader so the two never diverge on link safety).

  async function backfill() {
    backfilling = true;
    backfillMsg = null;
    try {
      await apiPost(`/v1/groups/${$page.params.id}/backfill`, {}, { auth: true });
      backfillMsg = 'Backfill queued · the collector deep-fetches all pages under throttle.';
    } catch (e) {
      backfillMsg = 'Failed: ' + e.message;
    }
    backfilling = false;
  }

  async function reply() {
    const message = replyText.trim();
    if (!message) return;
    submitting = true;
    replyMsg = null;
    try {
      await apiPost(`/v1/groups/${$page.params.id}/reply`, { message }, { auth: true });
      replyMsg = 'Queued. The collector posts it under throttle, then re-fetches to unlock.';
      replyText = '';
    } catch (e) {
      replyMsg = 'Failed: ' + e.message;
    }
    submitting = false;
  }
</script>

<main>
  <div class="head">
    <div class="crumb">
      <a class="slug-link" href="/reader">reader</a><span class="sep">/</span><span class="slug">messages</span>
    </div>
    <h1>Conversation</h1>
    {#if gated}<span class="gatehint">Contains [hide]-gated posts · reply to unlock.</span>{/if}
    <div class="searchrow">
      <input
        class="search"
        type="search"
        placeholder="Search this conversation…"
        bind:value={search}
        oninput={onSearch}
        aria-label="Search message bodies in this group" />
      {#if search.trim() && loaded}
        <span class="scount">
          {msgs.length}{#if total != null && total > msgs.length}<span class="oftotal"> / {total}</span>{/if}
          match{(total ?? msgs.length) === 1 ? '' : 'es'}
        </span>
      {/if}
    </div>
    {#if isForum}
      <div class="toolbar">
        <button class="btn ghost" disabled={backfilling} onclick={backfill}>Backfill deeper</button>
        <span class="hint">Sweeps keep page 1 (the leak + OP). Pull every page of this thread.</span>
        {#if backfillMsg}<span class="hint">{backfillMsg}</span>{/if}
      </div>
    {/if}
    {#if gated}
      <div class="replybox">
        <div class="rlabel">Reply to unlock (posted by the collector, throttled — type like a lazy human)</div>
        <div class="ractions">
          <textarea class="fin" rows="1" bind:value={replyText} placeholder="thanks, appreciated"></textarea>
          <button class="btn" disabled={submitting || !replyText.trim()} onclick={reply}>Queue reply</button>
        </div>
        {#if replyMsg}<span class="hint">{replyMsg}</span>{/if}
      </div>
    {/if}
  </div>

  <div class="body">
    {#if !loaded}
      <p class="pnote">Loading…</p>
    {:else if error}
      <p class="pnote err">Could not load: {error}</p>
    {:else if !msgs.length}
      <p class="pnote">{search.trim() ? `No posts in this conversation match “${search.trim()}”.` : 'No posts stored yet.'}</p>
    {:else}
      <ol class="posts" onclick={onGuardedClick}>
        {#each msgs as m}
          <li class="post" class:gatedpost={m.reply_gated}>
            <div class="pmeta">
              <span class="author">{m.author_display || m.author_username || 'unknown'}</span>
              <span class="ts">{fmt(m.ts)}</span>
              {#if m.reply_gated}<span class="badge">gated</span>{/if}
              {#if m.edited}<span class="badge edited">edited</span>{/if}
              {#each m.incident_labels ?? [] as l}<Badge tone={incidentTone(l)}>{incidentLabelName(l)}</Badge>{/each}
              {#if m.victim_country}<span class="ts">victim {m.victim_country}</span>{/if}
              {#if m.corrected_labels}
                <span class="corrtag">operator</span>
                {#each m.corrected_labels as l}<Badge tone={incidentTone(l)} dot>{incidentLabelName(l)}</Badge>{/each}
                {#if !m.corrected_labels.length}<Badge tone="neutral" dot>false positive</Badge>{/if}
              {/if}
              <button
                class="casebtn"
                title="Add to a case"
                onclick={() => (caseModalPost = { id: m.id, actor_id: m.actor_id, author: m.author_display || m.author_username, threadTitle: null })}>+ case</button>
            </div>
            {#if m.body_html}
              <div class="pbody">{@html prepare(m.body_html, boardOf(m.evidence_ref))}</div>
            {:else}
              <div class="pbody plain">{m.body}</div>
            {/if}

            <div class="relabel">
              {#if editId === m.id}
                <div class="chips">
                  {#each INCIDENT_LABELS as l}
                    <button type="button" class="chip" class:on={draft.has(l)} onclick={() => toggleLabel(l)}>{incidentLabelName(l)}</button>
                  {/each}
                </div>
                <div class="chips">
                  {#each REASON_PRESETS as r}
                    <button type="button" class="chip" class:on={!customReason && reason === r} onclick={() => { reason = r; customReason = false; }}>{r}</button>
                  {/each}
                  <button type="button" class="chip" class:on={customReason} onclick={() => { customReason = true; reason = ''; }}>Custom…</button>
                </div>
                {#if customReason}<input class="fin" type="text" bind:value={reason} placeholder="Custom reason (recorded to the audit chain)" />{/if}
                <div class="ra">
                  <button class="btn" disabled={!canSave} onclick={() => saveLabels(m)}>Save correction</button>
                  <button class="btn ghost" onclick={() => (editId = null)}>Cancel</button>
                  <span class="hint">reason required · empty labels = false positive</span>
                </div>
              {:else}
                <button class="editlink" onclick={() => startEdit(m)}>{m.corrected_labels ? 'edit correction' : 'correct labels'}</button>
              {/if}
              {#if editId === m.id && incidentEdit.msg}<span class="hint" class:err={incidentEdit.msg.startsWith('Failed')}>{incidentEdit.msg}</span>{/if}
            </div>
          </li>
        {/each}
      </ol>
      <p class="linkhint">Links are defanged · click once to reveal, twice to arm, three times to open in a new tab.</p>
    {/if}
  </div>
</main>

{#if caseModalPost}
  <CaseAddModal post={caseModalPost} onClose={() => (caseModalPost = null)} />
{/if}

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .head { padding: 20px 24px 0; }
  .crumb { display: flex; align-items: center; gap: 6px; font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .slug-link { color: var(--text-secondary); text-decoration: none; }
  .slug-link:hover { color: var(--accent); }
  h1 { margin: 4px 0 0; font-size: var(--fs-20); color: var(--text-body); }
  .gatehint { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--accent); }
  .searchrow { display: flex; align-items: center; gap: 10px; margin-top: 12px; }
  .search { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 6px 10px; min-width: 260px; }
  .search:focus { outline: none; border-color: var(--accent); }
  .scount { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); white-space: nowrap; }
  .oftotal { color: var(--text-muted); }
  .toolbar { display: flex; align-items: center; gap: 10px; margin-top: 8px; flex-wrap: wrap; }
  .btn.ghost { background: transparent; color: var(--accent-text); border: 1px solid var(--border-strong); }
  .btn.ghost:hover:not(:disabled) { border-color: var(--accent); }
  .body { flex: 1; min-height: 0; overflow: auto; padding: 12px 24px 24px; }
  .posts { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
  .post { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 14px; }
  .post.gatedpost { border-color: var(--accent); }
  .pmeta { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .author { color: var(--text-body); font-size: var(--fs-13); font-weight: 600; }
  .ts { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .badge { font-family: var(--font-sans); font-size: var(--fs-10); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--accent); border: 1px solid var(--accent); border-radius: 3px; padding: 0 5px; }
  .badge.edited { color: var(--text-faint); border-color: var(--border-strong); }
  .corrtag { font-family: var(--font-sans); font-size: var(--fs-10); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--accent-text); }
  .casebtn { appearance: none; margin-left: auto; padding: 2px 8px; border: 1px solid var(--border-strong); border-radius: 3px; background: transparent; color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--fs-10); text-transform: uppercase; letter-spacing: var(--tracking-label); cursor: pointer; }
  .casebtn:hover { border-color: var(--accent); color: var(--accent); }
  .relabel { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { background: var(--surface); border: 1px solid var(--border-strong); border-radius: 4px; color: var(--text-secondary); font-family: var(--font-sans); font-size: var(--fs-11); padding: 2px 8px; cursor: pointer; }
  .chip.on { background: var(--accent-fill); border-color: var(--accent); color: var(--text-body); }
  .ra { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .editlink { background: none; border: none; color: var(--text-faint); font-family: var(--font-sans); font-size: var(--fs-11); text-decoration: underline; cursor: pointer; padding: 0; }
  .editlink:hover { color: var(--accent); }
  .hint.err { color: var(--red-text); }
  .pbody { color: var(--text-body); font-size: var(--fs-13); line-height: 1.5; word-break: break-word; overflow-wrap: anywhere; }
  .pbody.plain { white-space: pre-wrap; font-family: var(--font-mono); font-size: var(--fs-12); }
  /* links come from sanitized {@html}, so they need :global to be reachable.
     Browser-default dark blue is unreadable on black; use the theme link token. */
  .pbody :global(a) { color: var(--link); text-decoration: underline; overflow-wrap: anywhere; cursor: pointer; }
  .pbody :global(a:hover) { color: var(--link-hover); }
  .pbody :global(a.armed1) { color: var(--accent-text); font-family: var(--font-mono); }
  .pbody :global(a.armed2) { color: var(--red-text); font-family: var(--font-mono); font-weight: 600; }
  .linkhint { margin: 10px 2px 0; font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); }
  .replybox { margin-top: 14px; display: flex; flex-direction: column; gap: 6px; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 14px; }
  .rlabel { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .fin { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; resize: vertical; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .ractions { display: flex; align-items: flex-start; gap: 10px; }
  .ractions .fin { flex: 1; }
  .btn { background: var(--accent); color: var(--black); border: none; border-radius: var(--radius); font-family: var(--font-sans); font-size: var(--fs-12); padding: 6px 12px; cursor: pointer; }
  .btn:disabled { opacity: 0.5; cursor: default; }
  .hint { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .pnote.err { color: var(--red-text); }
</style>
